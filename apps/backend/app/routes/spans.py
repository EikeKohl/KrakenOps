"""Span list endpoint with filters used by the dashboard."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import get_session

router = APIRouter(prefix="/v1", tags=["spans"])


@router.get("/spans")
def list_spans(
    session: Annotated[Session, Depends(get_session)],
    agent: str | None = Query(None, description="filter by service.name (agent)"),
    kind: str | None = Query(None, description="agent | tool | human_review"),
    since_ns: int | None = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}

    if agent:
        where.append("traces.service_name = :agent")
        params["agent"] = agent
    if kind:
        where.append("spans.tentacle_kind = :kind")
        params["kind"] = kind
    if since_ns is not None:
        where.append("spans.start_time_ns >= :since")
        params["since"] = since_ns

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = (
        "SELECT spans.span_id, spans.trace_id, spans.parent_span_id, spans.name,"
        " spans.otel_kind, spans.tentacle_kind, spans.start_time_ns, spans.end_time_ns,"
        " spans.status_code, spans.status_message, spans.attributes_json,"
        " spans.events_json, spans.needs_human_review,"
        " u.model, u.gen_ai_system, u.input_tokens, u.output_tokens, u.cost_usd,"
        " traces.service_name"
        " FROM spans"
        " JOIN traces ON traces.trace_id = spans.trace_id"
        " LEFT JOIN token_usage u ON u.span_id = spans.span_id"
        f" {where_sql}"
        " ORDER BY spans.start_time_ns DESC LIMIT :limit"
    )

    rows = session.exec(text(sql), params=params).all()  # type: ignore[call-arg]
    return {"spans": [_row_to_span(r) for r in rows]}


def _row_to_span(row: Any) -> dict[str, Any]:
    base = {
        "span_id": row[0],
        "trace_id": row[1],
        "parent_span_id": row[2],
        "name": row[3],
        "otel_kind": row[4],
        "tentacle_kind": row[5],
        "start_time_ns": row[6],
        "end_time_ns": row[7],
        "status_code": row[8],
        "status_message": row[9],
        "attributes": json.loads(row[10]),
        "events": json.loads(row[11]),
        "needs_human_review": bool(row[12]),
        "service_name": row[18],
    }
    if row[13] is not None:
        base["token_usage"] = {
            "model": row[13],
            "gen_ai_system": row[14],
            "input_tokens": row[15],
            "output_tokens": row[16],
            "cost_usd": row[17],
        }
    return base
