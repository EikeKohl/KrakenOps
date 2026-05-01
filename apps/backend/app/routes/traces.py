"""Trace ingest + read.

POST /v1/traces      — OTLP/HTTP protobuf ingest from the tentacle SDK
GET  /v1/traces      — paginated list of recent traces
GET  /v1/traces/{id} — a single trace with its complete span tree
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import text
from sqlmodel import Session

from app.db import engine
from app.db.pricing import lookup_cost
from app.db.session import get_session
from app.ingest import (
    NormalizedPayload,
    NormalizedSpan,
    NormalizedTokenUsage,
    decode_otlp,
    normalize,
    to_json,
)
from app.realtime import BUS

_log = logging.getLogger("krakenops.routes.traces")

router = APIRouter(prefix="/v1", tags=["traces"])


@router.post("/traces", status_code=status.HTTP_200_OK)
async def ingest_traces(request: Request) -> Response:
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")

    try:
        req = decode_otlp(body)
    except Exception as e:
        _log.warning("OTLP decode failed: %s", e)
        raise HTTPException(400, f"invalid OTLP payload: {e}") from e

    payload = normalize(req)
    _persist(payload)

    # OTLP/HTTP success response is an empty ExportTraceServiceResponse — we
    # can return an empty body with status 200; the SDK only checks the status.
    return Response(status_code=200)


@router.get("/traces")
def list_traces(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(50, ge=1, le=500),
    since_ns: int | None = Query(None, ge=0),
) -> dict[str, Any]:
    where = ""
    params: dict[str, Any] = {"limit": limit}
    if since_ns is not None:
        where = "WHERE started_at_ns >= :since"
        params["since"] = since_ns
    sql = (
        "SELECT trace_id, service_name, started_at_ns, ended_at_ns,"
        " span_count, has_human_review"
        f" FROM traces {where}"
        " ORDER BY started_at_ns DESC LIMIT :limit"
    )
    rows = session.exec(text(sql), params=params).all()  # type: ignore[call-arg]
    return {"traces": [_row_to_trace(r) for r in rows]}


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    trace_row = session.exec(
        text(
            "SELECT trace_id, service_name, started_at_ns, ended_at_ns,"
            " span_count, has_human_review"
            " FROM traces WHERE trace_id = :tid"
        ),
        params={"tid": trace_id},
    ).first()  # type: ignore[call-arg]
    if trace_row is None:
        raise HTTPException(404, "trace not found")

    span_rows = session.exec(
        text(
            "SELECT s.span_id, s.trace_id, s.parent_span_id, s.name, s.otel_kind,"
            " s.tentacle_kind, s.start_time_ns, s.end_time_ns,"
            " s.status_code, s.status_message,"
            " s.attributes_json, s.events_json, s.needs_human_review,"
            " u.model, u.gen_ai_system, u.input_tokens, u.output_tokens, u.cost_usd"
            " FROM spans s LEFT JOIN token_usage u ON u.span_id = s.span_id"
            " WHERE s.trace_id = :tid"
            " ORDER BY s.start_time_ns ASC"
        ),
        params={"tid": trace_id},
    ).all()  # type: ignore[call-arg]

    return {
        "trace": _row_to_trace(trace_row),
        "spans": [_row_to_span(r) for r in span_rows],
    }


# --- internals -----------------------------------------------------------


def _persist(payload: NormalizedPayload) -> None:
    """Write a decoded OTLP payload to SQLite, derive cost, fan out to WS subscribers."""
    usage_by_span = {u.span_id: u for u in payload.token_usages}

    with engine.begin() as conn:
        for span in payload.spans:
            _upsert_trace(conn, span, payload.service_name)
            _upsert_span(conn, span)
        for usage in payload.token_usages:
            _upsert_token_usage(conn, usage)

    # Fan-out happens AFTER commit so WS subscribers never see a span the
    # /v1/traces endpoint can't yet return.
    for span in payload.spans:
        summary = _ws_summary(span, payload.service_name, usage_by_span.get(span.span_id))
        BUS.publish("traces", summary)


def _ws_summary(
    span: NormalizedSpan,
    service_name: str,
    usage: NormalizedTokenUsage | None,
) -> dict[str, Any]:
    """Compact span summary suitable for live streaming. Full attributes/events stay in REST."""
    out: dict[str, Any] = {
        "span_id": span.span_id,
        "trace_id": span.trace_id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "tentacle_kind": span.tentacle_kind,
        "service_name": service_name,
        "start_time_ns": span.start_time_ns,
        "end_time_ns": span.end_time_ns,
        "status_code": span.status_code,
        "needs_human_review": span.needs_human_review,
    }
    if usage is not None:
        out["token_usage"] = {
            "model": usage.model,
            "gen_ai_system": usage.gen_ai_system,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": lookup_cost(engine, usage.model, usage.input_tokens, usage.output_tokens),
        }
    return out


def _upsert_trace(conn: Any, span: NormalizedSpan, service_name: str) -> None:
    conn.execute(
        text(
            "INSERT INTO traces"
            " (trace_id, service_name, started_at_ns, ended_at_ns,"
            "  span_count, has_human_review)"
            " VALUES (:tid, :svc, :start, :end, 1, :hr)"
            " ON CONFLICT(trace_id) DO UPDATE SET"
            "  service_name = excluded.service_name,"
            "  started_at_ns = MIN(traces.started_at_ns, excluded.started_at_ns),"
            "  ended_at_ns = MAX(COALESCE(traces.ended_at_ns, 0), excluded.ended_at_ns),"
            "  span_count = traces.span_count + 1,"
            "  has_human_review = MAX(traces.has_human_review, excluded.has_human_review)"
        ),
        {
            "tid": span.trace_id,
            "svc": service_name,
            "start": span.start_time_ns,
            "end": span.end_time_ns,
            "hr": int(span.needs_human_review),
        },
    )


def _upsert_span(conn: Any, span: NormalizedSpan) -> None:
    conn.execute(
        text(
            "INSERT INTO spans"
            " (span_id, trace_id, parent_span_id, name, otel_kind, tentacle_kind,"
            "  start_time_ns, end_time_ns, status_code, status_message,"
            "  attributes_json, events_json, needs_human_review)"
            " VALUES (:span_id, :trace_id, :parent, :name, :otel_kind, :tk,"
            "  :start, :end, :sc, :sm, :attrs, :events, :hr)"
            " ON CONFLICT(span_id) DO UPDATE SET"
            "  end_time_ns = excluded.end_time_ns,"
            "  status_code = excluded.status_code,"
            "  status_message = excluded.status_message,"
            "  attributes_json = excluded.attributes_json,"
            "  events_json = excluded.events_json,"
            "  needs_human_review = excluded.needs_human_review"
        ),
        {
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "parent": span.parent_span_id,
            "name": span.name,
            "otel_kind": span.otel_kind,
            "tk": span.tentacle_kind,
            "start": span.start_time_ns,
            "end": span.end_time_ns,
            "sc": span.status_code,
            "sm": span.status_message,
            "attrs": to_json(span.attributes),
            "events": to_json(span.events),
            "hr": int(span.needs_human_review),
        },
    )


def _upsert_token_usage(conn: Any, usage: NormalizedTokenUsage) -> None:
    cost = lookup_cost(engine, usage.model, usage.input_tokens, usage.output_tokens)
    conn.execute(
        text(
            "INSERT INTO token_usage"
            " (span_id, trace_id, gen_ai_system, model, input_tokens, output_tokens, cost_usd)"
            " VALUES (:span_id, :trace_id, :sys, :model, :inp, :out, :cost)"
            " ON CONFLICT(span_id) DO UPDATE SET"
            "  gen_ai_system = excluded.gen_ai_system,"
            "  model = excluded.model,"
            "  input_tokens = excluded.input_tokens,"
            "  output_tokens = excluded.output_tokens,"
            "  cost_usd = excluded.cost_usd"
        ),
        {
            "span_id": usage.span_id,
            "trace_id": usage.trace_id,
            "sys": usage.gen_ai_system,
            "model": usage.model,
            "inp": usage.input_tokens,
            "out": usage.output_tokens,
            "cost": cost,
        },
    )


def _row_to_trace(row: Any) -> dict[str, Any]:
    return {
        "trace_id": row[0],
        "service_name": row[1],
        "started_at_ns": row[2],
        "ended_at_ns": row[3],
        "span_count": row[4],
        "has_human_review": bool(row[5]),
    }


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
    }
    # token_usage fields (LEFT JOINed; may be NULL)
    if row[13] is not None:
        base["token_usage"] = {
            "model": row[13],
            "gen_ai_system": row[14],
            "input_tokens": row[15],
            "output_tokens": row[16],
            "cost_usd": row[17],
        }
    return base
