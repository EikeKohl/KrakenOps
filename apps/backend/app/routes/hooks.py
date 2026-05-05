"""Claude Code hook ingestion (ADR 0007).

Endpoints under ``/v1/hooks/claude/*`` accept the raw HTTP-hook payload
Claude Code POSTs when its plugin's hook configuration says so. The
payload schema is documented at https://code.claude.com/docs/en/hooks.md
— relevant fields: ``session_id``, ``tool_name``, ``tool_input``,
``hook_event_name``.

These routes:

- Upsert a workstream keyed ``(source="claude_code",
  external_id=session_id)`` if the OTel auto-discovery (ADR 0006) hasn't
  already done so.
- Persist the new TODO list on ``PostToolUse(TodoWrite)``.
- Mark ``ended_at_s`` on ``SessionEnd``.
- Republish a fresh ``workstreams`` snapshot on every change so the
  dashboard sees TODO progress within one round-trip.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.db import engine
from app.realtime import BUS
from app.workstreams import (
    end_workstream,
    list_active_workstreams,
    update_todos,
    upsert_external_workstream,
)

_log = logging.getLogger("krakenops.routes.hooks")

router = APIRouter(prefix="/v1/hooks/claude", tags=["claude-hooks"])


@router.post("/post-tool-use")
async def post_tool_use(request: Request) -> dict[str, Any]:
    """Claude Code's PostToolUse hook fires after every tool call.

    The plugin's matcher narrows this to ``TodoWrite`` only — but we still
    defensively check ``tool_name`` here so a misconfigured hook can't
    write garbage into the workstream's todos column.
    """
    payload = await _safe_json(request)
    session_id = _str(payload, "session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    tool_name = _str(payload, "tool_name") or ""

    ws_id = _ensure_workstream(session_id)

    if tool_name == "TodoWrite":
        todos = _coerce_todos(payload.get("tool_input"))
        update_todos(engine, ws_id, todos)
        BUS.publish(
            "workstreams", {"workstreams": list_active_workstreams(engine)},
        )
        return {"workstream_id": ws_id, "todos_count": len(todos)}

    # Non-TodoWrite: just keep the workstream warm.
    return {"workstream_id": ws_id, "todos_count": None}


@router.post("/session-start")
async def session_start(request: Request) -> dict[str, Any]:
    """Echoes the session_id so the agent can quote it back via MCP if it
    wants to be explicit (otherwise the heuristic fallback handles it)."""
    payload = await _safe_json(request)
    session_id = _str(payload, "session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    ws_id = _ensure_workstream(session_id)
    BUS.publish(
        "workstreams", {"workstreams": list_active_workstreams(engine)},
    )
    return {"workstream_id": ws_id, "session_id": session_id}


@router.post("/session-end")
async def session_end(request: Request) -> dict[str, Any]:
    payload = await _safe_json(request)
    session_id = _str(payload, "session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    ws_id = _ensure_workstream(session_id)
    end_workstream(engine, ws_id)
    BUS.publish(
        "workstreams", {"workstreams": list_active_workstreams(engine)},
    )
    return {"workstream_id": ws_id, "ended": True}


# --- internals -----------------------------------------------------------


async def _safe_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(400, f"invalid JSON body: {e}") from e
    if not isinstance(body, dict):
        raise HTTPException(400, "expected a JSON object")
    return body


def _str(d: dict[str, Any], key: str) -> str | None:
    v = d.get(key)
    return v if isinstance(v, str) else None


def _ensure_workstream(session_id: str) -> int:
    """Idempotent — auto-discovery may have already created the row."""
    label = f"Claude Code · sess {session_id[:8]}"
    return upsert_external_workstream(
        engine,
        source="claude_code",
        external_id=session_id,
        label=label,
        now_s=int(time.time()),
    )


def _coerce_todos(tool_input: Any) -> list[dict[str, Any]]:
    """Pull the TODO list out of TodoWrite's ``tool_input``.

    Claude Code's TodoWrite always rewrites the full list; ``tool_input``
    is shaped ``{"todos": [{"content", "activeForm", "status"}, ...]}``.
    We accept either that shape or the bare list (older Claude builds), and
    we filter out items that don't carry a ``content`` field — defensive
    against payload churn we don't control.
    """
    if isinstance(tool_input, list):
        candidates = tool_input
    elif isinstance(tool_input, dict):
        candidates = tool_input.get("todos") or []
    else:
        candidates = []

    out: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        status = item.get("status") if item.get("status") in {
            "pending", "in_progress", "completed",
        } else "pending"
        active_form = (
            item.get("activeForm") if isinstance(item.get("activeForm"), str) else None
        )
        out.append(
            {"content": content, "activeForm": active_form, "status": status}
        )
    return out
