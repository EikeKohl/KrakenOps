"""GitHub Projects → SQLite mirror (ADR 0002 + ADR 0006).

Per project: one async task. Each tick:

1. Fetch the project's items via the injected ``GitHubClient``.
2. Upsert the project row (`projects` table).
3. Upsert each ticket, stamping ``project_id`` and detecting status
   transitions vs. the previous tick.
4. Broadcast a fresh snapshot on the ``kanban`` topic.

KrakenOps is now read-only (ADR 0006): the auto-spawn-on-Todo dispatcher is
gone. The manual ``/v1/tickets/{id}/spawn`` endpoint still exists for users
who want to imperatively kick off a Tentacle agent. The poller's only job
is to mirror.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config_file import AgentConfig, FileConfig, GitHubProjectConfig, pick_agent_for
from app.poller.github import GitHubClient, ProjectSnapshot, TicketItem
from app.realtime import BUS

_log = logging.getLogger("krakenops.poller.loop")


# --- DB helpers -----------------------------------------------------------


def _upsert_project(conn: Any, snap: ProjectSnapshot, now_s: int) -> None:
    conn.execute(
        text(
            "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
            " VALUES (:id, :title, :owner, :now)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  title = excluded.title,"
            "  owner_login = excluded.owner_login,"
            "  last_seen_at_s = excluded.last_seen_at_s"
        ),
        {
            "id": snap.project_id,
            "title": snap.title,
            "owner": snap.owner_login,
            "now": now_s,
        },
    )


def _upsert_ticket(
    conn: Any,
    item: TicketItem,
    project_id: str,
    agent_name: str | None,
    now_s: int,
) -> None:
    conn.execute(
        text(
            "INSERT INTO tickets"
            " (id, title, status, url, agent, project_id, updated_at_s, last_seen_at_s)"
            " VALUES (:id, :title, :status, :url, :agent, :project_id, :now, :now)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  title = excluded.title,"
            "  status = excluded.status,"
            "  url = excluded.url,"
            "  agent = excluded.agent,"
            "  project_id = excluded.project_id,"
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
            "project_id": project_id,
            "now": now_s,
        },
    )


def _list_tickets(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, title, status, url, agent, updated_at_s, project_id"
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
            "project_id": r[6],
        }
        for r in rows
    ]


def _list_projects(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            "SELECT id, title, owner_login, last_seen_at_s"
            " FROM projects ORDER BY title"
        )
    ).all()
    return [
        {"id": r[0], "title": r[1], "owner_login": r[2], "last_seen_at_s": r[3]}
        for r in rows
    ]


# --- Single tick ----------------------------------------------------------


async def tick(
    engine: Engine,
    github: GitHubClient,
    agents: list[AgentConfig],
    publish: Callable[[str, Any], int] = BUS.publish,
) -> dict[str, Any]:
    """Run one poll cycle for one project. Returns a small summary dict.

    No subprocess dispatch (ADR 0006); the result dict no longer carries a
    ``spawned`` field — callers that asserted on it should look at the
    ``upserts`` count instead.
    """
    now_s = int(time.time())
    try:
        snap = await github.list_items()
    except Exception:
        _log.exception("github list_items failed for %s; will retry", github.project_id)
        return {"ok": False, "project_id": github.project_id, "upserts": 0}

    with engine.begin() as conn:
        _upsert_project(conn, snap, now_s)
        for item in snap.items:
            label = item.labels[0] if item.labels else None
            agent = pick_agent_for(label, agents)
            agent_name = agent.name if agent else None
            _upsert_ticket(conn, item, snap.project_id, agent_name, now_s)

    # Broadcast the full ticket snapshot — dashboard groups client-side.
    with engine.begin() as conn:
        ticket_snapshot = _list_tickets(conn)
        project_snapshot = _list_projects(conn)
    publish("kanban", {"tickets": ticket_snapshot, "projects": project_snapshot})

    return {
        "ok": True,
        "project_id": snap.project_id,
        "upserts": len(snap.items),
    }


# --- Long-running task ----------------------------------------------------


async def _project_loop(
    engine: Engine,
    github: GitHubClient,
    agents: list[AgentConfig],
    interval_s: int,
) -> None:
    _log.info(
        "github poller started for %s @ %ss interval", github.project_id, interval_s
    )
    try:
        while True:
            await tick(engine, github, agents)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _log.info("github poller stopped for %s", github.project_id)
        await github.aclose()
        raise


def start(
    engine: Engine,
    config: FileConfig,
    backend_endpoint: str,
    *,
    client_factory: Callable[[GitHubProjectConfig], GitHubClient] | None = None,
) -> tuple[list[asyncio.Task[None]], list[GitHubClient]]:
    """Spawn one poller task per configured project.

    Returns ``(tasks, clients)``. Both are empty when no GitHub config is
    present. The caller (lifespan) typically stashes ``clients`` on
    ``app.state`` so route handlers can dispatch / set status without
    re-reading config.

    ``backend_endpoint`` is unused in the read-only poller (ADR 0006) but
    kept in the signature so the manual `/v1/tickets/{id}/spawn` endpoint
    can still resolve it from app.state if needed in the future.
    """
    del backend_endpoint  # ADR 0006: no auto-spawn anymore.

    if not config.poller_enabled or config.github is None:
        _log.info("github poller dormant (no config)")
        return [], []

    if client_factory is None:
        from app.poller.github import GitHubGraphQLClient

        def client_factory(p: GitHubProjectConfig) -> GitHubClient:
            return GitHubGraphQLClient(config.github.pat, p.id)

    tasks: list[asyncio.Task[None]] = []
    clients: list[GitHubClient] = []
    for project in config.github.projects:
        client = client_factory(project)
        clients.append(client)
        tasks.append(
            asyncio.create_task(
                _project_loop(engine, client, config.agents, project.poll_interval_s),
                name=f"krakenops-poller-{project.id}",
            )
        )
    return tasks, clients
