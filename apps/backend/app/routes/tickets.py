"""Tickets: list (mirror of GitHub Projects) + spawn + resume commands.

See ADR 0002 (mirror) and ADR 0003 (commands).
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session

from app.config_file import pick_agent_for
from app.db import engine as engine_singleton
from app.db.session import get_session
from app.poller.orchestrator import dispatch_run

_log = logging.getLogger("krakenops.routes.tickets")

router = APIRouter(prefix="/v1", tags=["tickets"])


@router.get("/tickets")
def list_tickets(session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    rows = session.exec(  # type: ignore[call-arg]
        text(
            "SELECT id, title, status, url, agent, updated_at_s, last_seen_at_s, project_id"
            " FROM tickets ORDER BY updated_at_s DESC"
        )
    ).all()
    return {
        "tickets": [
            {
                "id": r[0],
                "title": r[1],
                "status": r[2],
                "url": r[3],
                "agent": r[4],
                "updated_at_s": r[5],
                "last_seen_at_s": r[6],
                "project_id": r[7],
            }
            for r in rows
        ]
    }


def _client_for_ticket(request: Request, project_id: str | None) -> Any:
    """Return the GitHubClient for a ticket's project (ADR 0006).

    Falls back to the legacy single ``github_client`` attribute when the
    list isn't present (older tests + fake clients) so the migration
    remains backwards compatible.
    """
    clients = getattr(request.app.state, "github_clients", None) or []
    if project_id:
        for c in clients:
            if getattr(c, "project_id", None) == project_id:
                return c
    legacy = getattr(request.app.state, "github_client", None)
    if legacy is not None:
        return legacy
    return clients[0] if clients else None


@router.post("/tickets/{ticket_id}/spawn", status_code=202)
async def spawn_ticket(ticket_id: str, request: Request) -> dict[str, Any]:
    """Manually run the configured agent for a ticket. See ADR 0003."""
    agents = getattr(request.app.state, "agents", []) or []
    backend_endpoint = getattr(
        request.app.state, "backend_endpoint", "http://127.0.0.1:8787/v1/traces"
    )

    with engine_singleton.begin() as conn:
        ticket_row = conn.execute(
            text(
                "SELECT title, status, agent, project_id FROM tickets WHERE id = :id"
            ),
            {"id": ticket_id},
        ).first()
        if ticket_row is None:
            raise HTTPException(404, "ticket not found")
        title, _status, persisted_agent, project_id = ticket_row

        running = conn.execute(
            text(
                "SELECT 1 FROM agent_runs WHERE ticket_id = :id AND status = 'running' LIMIT 1"
            ),
            {"id": ticket_id},
        ).first()
        if running is not None:
            raise HTTPException(409, "agent already running for this ticket")

    github = _client_for_ticket(request, project_id)
    if github is None:
        raise HTTPException(503, "github poller dormant; nothing to spawn through")

    # Prefer the agent the poller previously matched (so spawn behaves the
    # same as auto-dispatch); fall back to the catch-all if any.
    agent = next((a for a in agents if a.name == persisted_agent), None)
    if agent is None:
        agent = pick_agent_for(None, agents)
    if agent is None:
        raise HTTPException(400, "no agent mapping matches this ticket")

    _ = dispatch_run(
        engine=engine_singleton,
        github=github,
        ticket_id=ticket_id,
        ticket_title=title,
        agent=agent,
        backend_endpoint=backend_endpoint,
    )
    # Yield to the loop so the just-scheduled task can execute its
    # synchronous prefix (which inserts the agent_runs row before the
    # first await). After this, the row is queryable.
    import asyncio
    await asyncio.sleep(0)
    # The orchestrator wrote a row at start_run; surface its id by peeking
    # at the most-recent row for this ticket.
    with engine_singleton.begin() as conn:
        run_id = conn.execute(
            text(
                "SELECT id FROM agent_runs WHERE ticket_id = :id"
                " ORDER BY started_at_s DESC LIMIT 1"
            ),
            {"id": ticket_id},
        ).scalar()
    _log.info("spawn ticket=%s agent=%s run_id=%s", ticket_id, agent.name, run_id)
    return {"run_id": int(run_id) if run_id is not None else None, "agent": agent.name}


@router.post("/tickets/{ticket_id}/resume")
async def resume_ticket(ticket_id: str, request: Request) -> dict[str, Any]:
    """Move a `Needs Human Review` ticket back to Todo. See ADR 0003."""
    with engine_singleton.begin() as conn:
        project_row = conn.execute(
            text("SELECT project_id FROM tickets WHERE id = :id"), {"id": ticket_id},
        ).first()
    project_id = project_row[0] if project_row else None
    github = _client_for_ticket(request, project_id)
    if github is None:
        raise HTTPException(503, "github poller dormant; cannot update remote status")

    with engine_singleton.begin() as conn:
        row = conn.execute(
            text("SELECT status FROM tickets WHERE id = :id"), {"id": ticket_id},
        ).first()
        if row is None:
            raise HTTPException(404, "ticket not found")
        if row[0] != "Needs Human Review":
            raise HTTPException(409, f"ticket is in {row[0]!r}, not 'Needs Human Review'")

    try:
        await github.set_status(ticket_id, "Todo")
    except Exception as e:
        _log.exception("github set_status failed for ticket=%s", ticket_id)
        raise HTTPException(502, f"github update failed: {e}") from e

    # Optimistic local update so the dashboard reflects the change immediately
    # rather than waiting for the next poll.
    with engine_singleton.begin() as conn:
        conn.execute(
            text("UPDATE tickets SET status = 'Todo', updated_at_s = :ts WHERE id = :id"),
            {"ts": int(time.time()), "id": ticket_id},
        )

    return {"status": "Todo"}
