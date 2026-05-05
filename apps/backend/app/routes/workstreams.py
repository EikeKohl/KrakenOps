"""Workstream REST surface (ADR 0006).

GET    /v1/workstreams              — list active + recent workstreams.
POST   /v1/workstreams/{id}/bind    — bind to a ticket (manual claim).
POST   /v1/workstreams/{id}/unbind  — drop the ticket binding.

The auto-discovery subscriber populates the underlying table from the
``events`` topic; bindings are user-driven (or, in Phase B, MCP-driven).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db import engine
from app.realtime import BUS
from app.workstreams.repo import (
    bind_workstream,
    list_active_workstreams,
    list_workstreams,
    resolve_workstream,
    unbind_workstream,
    update_todos,
    upsert_external_workstream,
)

router = APIRouter(prefix="/v1", tags=["workstreams"])


class BindRequest(BaseModel):
    ticket_id: str
    project_id: str | None = None


class ClaimRequest(BaseModel):
    """ADR 0007 — MCP-friendly bind: resolve the calling session's
    workstream server-side rather than requiring the agent to know its
    workstream id."""

    ticket_id: str
    session_id: str | None = None
    project_id: str | None = None


class TodosRequest(BaseModel):
    todos: list[dict]
    session_id: str | None = None
    # ADR 0008: tentacle agents pass source="tentacle"; default keeps
    # the Claude Code path backwards-compatible.
    source: str = "claude_code"


class ClaimRequestSourced(ClaimRequest):
    source: str = "claude_code"


class RegisterRequest(BaseModel):
    """ADR 0008 — bootstrap a workstream for any source.

    Idempotent on ``(source, external_id)``. Used by the tentacle SDK
    (``tentacle.register_workstream``) and by future agent runtimes
    that don't have OTel auto-discovery.
    """

    source: str
    external_id: str
    label: str | None = None


@router.get("/workstreams")
def list_endpoint(
    active_only: bool = Query(True, description="hide rows older than 5 min"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    if active_only:
        rows = list_active_workstreams(engine)
    else:
        rows = list_workstreams(engine, limit=limit)
    return {"workstreams": rows}


@router.post("/workstreams/{ws_id}/bind")
def bind_endpoint(ws_id: int, body: BindRequest) -> dict[str, Any]:
    ok = bind_workstream(
        engine,
        ws_id,
        ticket_id=body.ticket_id,
        project_id=body.project_id,
        method="manual",
    )
    if not ok:
        raise HTTPException(404, "workstream or ticket not found")
    BUS.publish("workstreams", {"workstreams": list_active_workstreams(engine)})
    return {"bound": True, "bind_method": "manual"}


@router.post("/workstreams/{ws_id}/unbind")
def unbind_endpoint(ws_id: int) -> dict[str, Any]:
    ok = unbind_workstream(engine, ws_id)
    if not ok:
        raise HTTPException(404, "workstream not found")
    BUS.publish("workstreams", {"workstreams": list_active_workstreams(engine)})
    return {"bound": False}


@router.post("/workstreams/claim")
def claim_endpoint(body: ClaimRequestSourced) -> dict[str, Any]:
    """ADR 0007 (Claude Code) + ADR 0008 (tentacle) — bind the calling
    session's workstream to a ticket.

    Resolves the workstream via ``(source, session_id)`` if given, else
    by the most-recently-active workstream of that source. Marks the
    binding ``method="mcp"`` — ADR 0008 keeps the same label so the
    dashboard's existing ``via MCP`` badge applies to tentacle agents
    too.
    """
    ws_id = resolve_workstream(engine, source=body.source, session_id=body.session_id)
    if ws_id is None:
        raise HTTPException(
            404,
            f"no active {body.source} workstream — register one first"
            " (tentacle.register_workstream / start a Claude Code session)"
            " or pass an explicit session_id",
        )
    ok = bind_workstream(
        engine,
        ws_id,
        ticket_id=body.ticket_id,
        project_id=body.project_id,
        method="mcp",
    )
    if not ok:
        raise HTTPException(404, "ticket not found")
    BUS.publish("workstreams", {"workstreams": list_active_workstreams(engine)})
    return {"bound": True, "bind_method": "mcp", "workstream_id": ws_id}


@router.post("/workstreams/todos")
def todos_endpoint(body: TodosRequest) -> dict[str, Any]:
    """ADR 0007 (Claude Code) + ADR 0008 (tentacle) — replace the
    calling session's TODO list.

    The hook route ``/v1/hooks/claude/post-tool-use`` covers the
    automatic Claude Code case. This endpoint exists for explicit MCP
    calls and the tentacle SDK's ``set_todos`` — both share the same
    payload shape with an optional ``source`` discriminator.
    """
    ws_id = resolve_workstream(engine, source=body.source, session_id=body.session_id)
    if ws_id is None:
        raise HTTPException(404, f"no active {body.source} workstream")
    update_todos(engine, ws_id, body.todos)
    BUS.publish("workstreams", {"workstreams": list_active_workstreams(engine)})
    return {"workstream_id": ws_id, "todos_count": len(body.todos)}


@router.post("/workstreams/register")
def register_endpoint(body: RegisterRequest) -> dict[str, Any]:
    """ADR 0008 — explicit workstream bootstrap for any source.

    Idempotent on ``(source, external_id)``: a second call with the same
    pair just refreshes ``last_seen_at_s`` and returns the existing id.
    """
    source = body.source.strip()
    if not source:
        raise HTTPException(400, "source required")
    external_id = body.external_id.strip()
    if not external_id:
        raise HTTPException(400, "external_id required")
    label = body.label or f"{source} · {external_id[:8]}"
    ws_id = upsert_external_workstream(
        engine, source=source, external_id=external_id, label=label,
    )
    BUS.publish("workstreams", {"workstreams": list_active_workstreams(engine)})
    return {
        "workstream_id": ws_id,
        "source": source,
        "external_id": external_id,
    }
