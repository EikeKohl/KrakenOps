"""GitHub Projects → SQLite mirror + agent dispatch.

Single async task. Each tick:

1. Fetch the project's items via the injected `GitHubClient`.
2. Upsert into the `tickets` table; mark stale rows.
3. Broadcast a snapshot on the `kanban` topic.
4. For any ticket transitioning *into* "Todo" that isn't already running,
   look up an agent mapping and spawn an orchestrator run as a fire-and-forget
   task. The orchestrator updates GitHub when the run completes.

If GitHub is unreachable or the query errors, we log + sleep + retry on the
next interval. The poller never crashes the process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config_file import AgentConfig, FileConfig, pick_agent_for
from app.poller.github import GitHubClient, TicketItem
from app.poller.orchestrator import run_agent
from app.realtime import BUS

_log = logging.getLogger("krakenops.poller.loop")


# --- DB helpers -----------------------------------------------------------


def _upsert_ticket(conn: Any, item: TicketItem, agent_name: str | None, now_s: int) -> None:
    conn.execute(
        text(
            "INSERT INTO tickets (id, title, status, url, agent, updated_at_s, last_seen_at_s)"
            " VALUES (:id, :title, :status, :url, :agent, :now, :now)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  title = excluded.title,"
            "  status = excluded.status,"
            "  url = excluded.url,"
            "  agent = excluded.agent,"
            "  updated_at_s = CASE"
            "    WHEN tickets.status != excluded.status THEN excluded.updated_at_s"
            "    ELSE tickets.updated_at_s END,"
            "  last_seen_at_s = excluded.last_seen_at_s"
        ),
        {
            "id": item.id,
            "title": item.title,
            "status": item.status,
            "url": item.url,
            "agent": agent_name,
            "now": now_s,
        },
    )


def _list_tickets(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, title, status, url, agent, updated_at_s"
            " FROM tickets ORDER BY updated_at_s DESC"
        )
    ).all()
    return [
        {
            "id": r[0],
            "title": r[1],
            "status": r[2],
            "url": r[3],
            "agent": r[4],
            "updated_at_s": r[5],
        }
        for r in rows
    ]


def _has_running_run(conn: Any, ticket_id: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM agent_runs WHERE ticket_id = :tid AND status = 'running' LIMIT 1"),
        {"tid": ticket_id},
    ).first()
    return row is not None


# --- Single tick ----------------------------------------------------------


DispatchFn = Callable[..., asyncio.Task]


def _default_dispatch(
    *,
    engine: Engine,
    github: GitHubClient,
    ticket_id: str,
    ticket_title: str,
    agent: AgentConfig,
    backend_endpoint: str,
) -> asyncio.Task:
    return asyncio.create_task(
        run_agent(
            engine=engine,
            github=github,
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            agent=agent,
            backend_endpoint=backend_endpoint,
        ),
        name=f"krakenops-run-{ticket_id}",
    )


async def tick(
    engine: Engine,
    github: GitHubClient,
    agents: list[AgentConfig],
    backend_endpoint: str,
    publish: Callable[[str, Any], int] = BUS.publish,
    dispatch: DispatchFn | None = None,
) -> dict[str, Any]:
    """Run one poll cycle. Returns a small summary dict for telemetry/tests."""
    now_s = int(time.time())
    try:
        items = await github.list_items()
    except Exception:
        _log.exception("github list_items failed; will retry on next tick")
        return {"ok": False, "items": 0, "spawned": []}

    # Track which tickets transitioned into Todo (or arrived in Todo for the
    # first time). We dispatch agents only for those.
    spawned: list[str] = []
    with engine.begin() as conn:
        prior_status = {
            r[0]: r[1]
            for r in conn.execute(text("SELECT id, status FROM tickets")).all()
        }

        for item in items:
            label = item.labels[0] if item.labels else None
            agent = pick_agent_for(label, agents)
            agent_name = agent.name if agent else None
            _upsert_ticket(conn, item, agent_name, now_s)

        # Diff after upsert so we know who is in Todo "now" and was not last poll.
        for item in items:
            if item.status != "Todo":
                continue
            was_todo = prior_status.get(item.id) == "Todo"
            if was_todo:
                continue
            label = item.labels[0] if item.labels else None
            agent = pick_agent_for(label, agents)
            if agent is None:
                _log.info("ticket %s entered Todo but no agent matched label=%r", item.id, label)
                continue
            if _has_running_run(conn, item.id):
                continue
            spawned.append(item.id)

    # Fire-and-forget orchestrator runs. Each updates GitHub when it completes.
    do_dispatch = dispatch or _default_dispatch
    for ticket_id in spawned:
        item = next(i for i in items if i.id == ticket_id)
        label = item.labels[0] if item.labels else None
        agent = pick_agent_for(label, agents)
        if agent is None:
            continue
        do_dispatch(
            engine=engine,
            github=github,
            ticket_id=ticket_id,
            ticket_title=item.title,
            agent=agent,
            backend_endpoint=backend_endpoint,
        )

    # Broadcast the full ticket snapshot on the kanban topic.
    with engine.begin() as conn:
        snapshot = _list_tickets(conn)
    publish("kanban", {"tickets": snapshot})

    return {"ok": True, "items": len(items), "spawned": spawned}


# --- Long-running task ----------------------------------------------------


async def loop(
    engine: Engine,
    github: GitHubClient,
    agents: list[AgentConfig],
    interval_s: int,
    backend_endpoint: str,
) -> None:
    _log.info("github poller started @ %ss interval", interval_s)
    try:
        while True:
            await tick(engine, github, agents, backend_endpoint)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _log.info("github poller stopped")
        await github.aclose()
        raise


def start(
    engine: Engine,
    config: FileConfig,
    backend_endpoint: str,
    *,
    client_factory: Callable[..., GitHubClient] | None = None,
) -> tuple[asyncio.Task[None] | None, GitHubClient | None]:
    """Construct the right GitHubClient and spawn the poller task.

    Returns ``(task, client)``. Both are ``None`` when no GitHub config is
    present. The caller (lifespan) typically stashes ``client`` on
    ``app.state`` so route handlers can dispatch / set status without
    re-reading config.
    """
    if not config.poller_enabled or config.github is None:
        _log.info("github poller dormant (no config)")
        return None, None

    if client_factory is None:
        from app.poller.github import GitHubGraphQLClient

        client = GitHubGraphQLClient(config.github.pat, config.github.project_id)
    else:
        client = client_factory()

    task = asyncio.create_task(
        loop(engine, client, config.agents, config.github.poll_interval_s, backend_endpoint),
        name="krakenops-poller",
    )
    return task, client
