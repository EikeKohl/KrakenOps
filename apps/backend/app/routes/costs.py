"""Cost rollups (ADR 0001 + ADR 0008).

Two grouping modes:
- ``group_by=model`` (default) — token_usage joined to spans, summed by model.
- ``group_by=ticket`` — Claude Code's ``claude_code.cost.usage`` external
  metrics joined through ``workstreams.external_id`` to ``tickets.id`` and
  ``projects.id``. Tentacle workstreams report ``cost_usd=0`` for now;
  span↔workstream linkage is pending the future ``traces.workstream_session_id``
  column (ADR 0009-tbd).
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import get_session

router = APIRouter(prefix="/v1", tags=["costs"])

_WINDOWS_NS = {
    "1h": 60 * 60 * 1_000_000_000,
    "24h": 24 * 60 * 60 * 1_000_000_000,
    "7d": 7 * 24 * 60 * 60 * 1_000_000_000,
}


@router.get("/costs")
def costs(
    session: Annotated[Session, Depends(get_session)],
    window: str = Query("24h"),
    group_by: str = Query("model", pattern="^(model|ticket)$"),
) -> dict[str, Any]:
    if window not in _WINDOWS_NS:
        raise HTTPException(400, f"window must be one of {list(_WINDOWS_NS)}")
    since_ns = time.time_ns() - _WINDOWS_NS[window]

    if group_by == "ticket":
        return _by_ticket(session, window=window, since_ns=since_ns)
    return _by_model(session, window=window, since_ns=since_ns)


# --- model rollup --------------------------------------------------------


def _by_model(session: Session, *, window: str, since_ns: int) -> dict[str, Any]:
    rows = session.exec(  # type: ignore[call-arg]
        text(
            "SELECT u.model, COUNT(*) AS calls,"
            " SUM(u.input_tokens) AS input_tokens,"
            " SUM(u.output_tokens) AS output_tokens,"
            " SUM(COALESCE(u.cost_usd, 0)) AS cost_usd"
            " FROM token_usage u"
            " JOIN spans s ON s.span_id = u.span_id"
            " WHERE s.start_time_ns >= :since"
            " GROUP BY u.model"
            " ORDER BY cost_usd DESC"
        ),
        params={"since": since_ns},
    ).all()

    by_model = [
        {
            "model": r[0],
            "calls": int(r[1]),
            "input_tokens": int(r[2] or 0),
            "output_tokens": int(r[3] or 0),
            "cost_usd": float(r[4] or 0.0),
        }
        for r in rows
    ]
    total = round(sum(m["cost_usd"] for m in by_model), 8)
    return {
        "window": window,
        "since_ns": since_ns,
        "total_cost_usd": total,
        "by_model": by_model,
    }


# --- ticket rollup -------------------------------------------------------


def _by_ticket(session: Session, *, window: str, since_ns: int) -> dict[str, Any]:
    """Sum Claude Code cost-usage metrics through their session.id to
    the bound ticket.

    SQLite's JSON1 extension is bundled by default with the sqlite that
    ships with Python on macOS; we use ``json_extract`` to pull
    ``session.id`` out of ``external_metrics.attributes_json``.
    """
    rows = session.exec(  # type: ignore[call-arg]
        text(
            "SELECT t.id, t.title, t.project_id, p.title AS project_title,"
            " SUM(em.value) AS cost_usd, COUNT(em.id) AS calls"
            " FROM external_metrics em"
            " JOIN workstreams w"
            "   ON w.source = 'claude_code'"
            "  AND w.external_id = json_extract(em.attributes_json, '$.\"session.id\"')"
            " JOIN tickets t ON t.id = w.ticket_id"
            " LEFT JOIN projects p ON p.id = t.project_id"
            " WHERE em.metric_name = 'claude_code.cost.usage'"
            "   AND em.ts_ns >= :since"
            " GROUP BY t.id, t.title, t.project_id, project_title"
            " ORDER BY cost_usd DESC"
        ),
        params={"since": since_ns},
    ).all()

    by_ticket = [
        {
            "ticket_id": r[0],
            "ticket_title": r[1],
            "project_id": r[2],
            "project_title": r[3],
            "cost_usd": float(r[4] or 0.0),
            "calls": int(r[5] or 0),
        }
        for r in rows
    ]
    total = round(sum(t["cost_usd"] for t in by_ticket), 8)
    return {
        "window": window,
        "since_ns": since_ns,
        "total_cost_usd": total,
        "by_ticket": by_ticket,
    }
