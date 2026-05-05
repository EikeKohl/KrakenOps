"""External OTLP logs/events ingest (ADR 0005).

POST /v1/logs — OTLP/HTTP-protobuf ``ExportLogsServiceRequest`` body.

Each record produces one ``external_events`` row plus one ``events`` topic
broadcast envelope ``{"kind": "event", ...}``. The ``prompt.id`` /
``session.id`` attributes are pulled into indexed columns so the dashboard
can group events by prompt without a JSON scan.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from app.db import engine
from app.ingest.otel_logs import (
    NormalizedExternalEvent,
    decode_otlp_logs,
    normalize_logs,
)
from app.realtime import BUS

_log = logging.getLogger("krakenops.routes.logs_ingest")

router = APIRouter(prefix="/v1", tags=["external-events"])


@router.post("/logs", status_code=status.HTTP_200_OK)
async def ingest_logs(request: Request) -> dict[str, int]:
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")

    try:
        req = decode_otlp_logs(body)
    except Exception as e:
        _log.warning("OTLP logs decode failed: %s", e)
        raise HTTPException(400, f"invalid OTLP payload: {e}") from e

    payload = normalize_logs(req)
    _persist(payload.events)

    for ev in payload.events:
        BUS.publish("events", _ws_envelope(ev))

    return {"received": len(payload.events)}


# --- internals -----------------------------------------------------------


def _persist(events: list[NormalizedExternalEvent]) -> None:
    if not events:
        return
    with engine.begin() as conn:
        for ev in events:
            conn.execute(
                text(
                    "INSERT INTO external_events"
                    " (service_name, event_name, prompt_id, session_id,"
                    "  attributes_json, observed_at_ns)"
                    " VALUES (:svc, :name, :pid, :sid, :attrs, :ts)"
                ),
                {
                    "svc": ev.service_name,
                    "name": ev.event_name,
                    "pid": ev.prompt_id,
                    "sid": ev.session_id,
                    "attrs": json.dumps(ev.attributes, sort_keys=True, default=str),
                    "ts": ev.observed_at_ns,
                },
            )


def _ws_envelope(ev: NormalizedExternalEvent) -> dict[str, Any]:
    return {
        "kind": "event",
        "service_name": ev.service_name,
        "event_name": ev.event_name,
        "prompt_id": ev.prompt_id,
        "session_id": ev.session_id,
        "attributes": ev.attributes,
        "observed_at_ns": ev.observed_at_ns,
    }
