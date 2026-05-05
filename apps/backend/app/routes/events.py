"""Historical external events lookup (ADR 0005).

GET /v1/events?service=&limit=&since=

The dashboard uses this to backfill its ``events`` panel before the WS
stream starts producing fresh records.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import get_session

router = APIRouter(prefix="/v1", tags=["external-events"])


@router.get("/events")
def list_events(
    session: Annotated[Session, Depends(get_session)],
    service: str | None = Query(None, description="filter by service.name"),
    limit: int = Query(100, ge=1, le=500),
    since: int | None = Query(None, ge=0, description="ns timestamp lower bound"),
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}

    if service:
        where.append("service_name = :svc")
        params["svc"] = service
    if since is not None:
        where.append("observed_at_ns >= :since")
        params["since"] = since

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = (
        "SELECT id, service_name, event_name, prompt_id, session_id,"
        " attributes_json, observed_at_ns"
        f" FROM external_events {where_sql}"
        " ORDER BY observed_at_ns DESC LIMIT :limit"
    )
    rows = session.exec(text(sql), params=params).all()  # type: ignore[call-arg]
    return {"events": [_row_to_dict(r) for r in rows]}


def _row_to_dict(row: Any) -> dict[str, Any]:
    # `kind` matches the WS envelope discriminator (`ExternalActivity` on the
    # dashboard) so REST-seeded records and live frames share one type.
    return {
        "kind": "event",
        "id": int(row[0]),
        "service_name": row[1],
        "event_name": row[2],
        "prompt_id": row[3],
        "session_id": row[4],
        "attributes": json.loads(row[5]) if row[5] else {},
        "observed_at_ns": int(row[6]),
    }
