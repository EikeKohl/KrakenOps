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
    unbind_workstream,
)

router = APIRouter(prefix="/v1", tags=["workstreams"])


class BindRequest(BaseModel):
    ticket_id: str
    project_id: str | None = None


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
