"""Database operations for the ``workstreams`` table (ADR 0006).

Pure SQL, no FastAPI / asyncio dependencies — keeps the subscriber and the
HTTP routes both able to consume this without coupling.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

# A workstream is "active" if its last_seen_at_s falls within this window.
# Outside of it the row stays in the table but the dashboard hides it.
ACTIVE_WINDOW_S = 5 * 60


def upsert_external_workstream(
    engine: Engine,
    *,
    source: str,
    external_id: str,
    label: str,
    now_s: int | None = None,
) -> int:
    """Insert (or refresh ``last_seen_at_s`` of) a workstream row keyed by
    ``(source, external_id)``. Returns the workstream id.

    Used by the auto-discovery subscriber. Bind state, label, and project
    affinity are *not* touched on subsequent observations — that's the job
    of bind_workstream and (in Phase B) the MCP set_todos tool.
    """
    ts = now_s if now_s is not None else int(time.time())
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                "SELECT id FROM workstreams"
                " WHERE source = :source AND external_id = :ext"
            ),
            {"source": source, "ext": external_id},
        ).first()
        if existing is not None:
            ws_id = int(existing[0])
            conn.execute(
                text(
                    "UPDATE workstreams SET last_seen_at_s = :ts WHERE id = :id"
                ),
                {"ts": ts, "id": ws_id},
            )
            return ws_id
        cur = conn.execute(
            text(
                "INSERT INTO workstreams"
                " (source, external_id, label, started_at_s, last_seen_at_s)"
                " VALUES (:source, :ext, :label, :ts, :ts)"
            ),
            {"source": source, "ext": external_id, "label": label, "ts": ts},
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def update_todos(
    engine: Engine, workstream_id: int, todos: list[dict[str, Any]]
) -> None:
    """Replace a workstream's TODO list. ADR 0006 §"todos_json"."""
    now_s = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE workstreams SET"
                " todos_json = :todos,"
                " todos_updated_at_s = :ts,"
                " last_seen_at_s = :ts"
                " WHERE id = :id"
            ),
            {"todos": json.dumps(todos), "ts": now_s, "id": workstream_id},
        )


def bind_workstream(
    engine: Engine,
    workstream_id: int,
    *,
    ticket_id: str,
    project_id: str | None,
    method: str,
) -> bool:
    """Bind ``workstream_id`` to a ticket. Returns True on success.

    Refuses unknown workstream / ticket ids (returns False so the route
    layer can map to 404 without leaking SQL).
    """
    with engine.begin() as conn:
        ws_exists = conn.execute(
            text("SELECT 1 FROM workstreams WHERE id = :id"), {"id": workstream_id},
        ).first()
        if ws_exists is None:
            return False
        ticket_row = conn.execute(
            text("SELECT project_id FROM tickets WHERE id = :id"), {"id": ticket_id},
        ).first()
        if ticket_row is None:
            return False
        # Prefer the project_id supplied by the caller; otherwise inherit from
        # the ticket's own project_id (filled by the multi-project poller).
        resolved_project_id = project_id or ticket_row[0]
        conn.execute(
            text(
                "UPDATE workstreams SET"
                " ticket_id = :tid, project_id = :pid, bind_method = :m,"
                " last_seen_at_s = :ts"
                " WHERE id = :id"
            ),
            {
                "tid": ticket_id,
                "pid": resolved_project_id,
                "m": method,
                "ts": int(time.time()),
                "id": workstream_id,
            },
        )
        return True


def unbind_workstream(engine: Engine, workstream_id: int) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE workstreams SET"
                " ticket_id = NULL, project_id = NULL, bind_method = NULL,"
                " last_seen_at_s = :ts"
                " WHERE id = :id"
            ),
            {"ts": int(time.time()), "id": workstream_id},
        )
        return (result.rowcount or 0) > 0


def end_workstream(engine: Engine, workstream_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE workstreams SET ended_at_s = :ts WHERE id = :id AND ended_at_s IS NULL"
            ),
            {"ts": int(time.time()), "id": workstream_id},
        )


def find_by_external(
    engine: Engine, *, source: str, external_id: str
) -> int | None:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM workstreams"
                " WHERE source = :source AND external_id = :ext"
            ),
            {"source": source, "ext": external_id},
        ).first()
    return int(row[0]) if row else None


def list_workstreams(engine: Engine, *, limit: int = 100) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, source, external_id, label, ticket_id, project_id,"
                " bind_method, started_at_s, last_seen_at_s, ended_at_s,"
                " todos_json, todos_updated_at_s"
                " FROM workstreams ORDER BY last_seen_at_s DESC LIMIT :limit"
            ),
            {"limit": limit},
        ).all()
    return [_row_to_dict(r) for r in rows]


def list_active_workstreams(
    engine: Engine, *, now_s: int | None = None
) -> list[dict[str, Any]]:
    """Workstreams whose last_seen falls inside ACTIVE_WINDOW_S and which
    haven't been explicitly ended."""
    cutoff = (now_s if now_s is not None else int(time.time())) - ACTIVE_WINDOW_S
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, source, external_id, label, ticket_id, project_id,"
                " bind_method, started_at_s, last_seen_at_s, ended_at_s,"
                " todos_json, todos_updated_at_s"
                " FROM workstreams"
                " WHERE ended_at_s IS NULL AND last_seen_at_s >= :cutoff"
                " ORDER BY last_seen_at_s DESC"
            ),
            {"cutoff": cutoff},
        ).all()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    raw_todos = row[10]
    try:
        todos = json.loads(raw_todos) if raw_todos else []
    except json.JSONDecodeError:
        todos = []
    return {
        "id": int(row[0]),
        "source": row[1],
        "external_id": row[2],
        "label": row[3],
        "ticket_id": row[4],
        "project_id": row[5],
        "bind_method": row[6],
        "started_at_s": int(row[7]),
        "last_seen_at_s": int(row[8]),
        "ended_at_s": int(row[9]) if row[9] is not None else None,
        "todos": todos,
        "todos_updated_at_s": int(row[11]) if row[11] is not None else None,
    }
