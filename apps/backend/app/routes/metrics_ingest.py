"""External OTLP metrics ingest (ADR 0005).

POST /v1/metrics — OTLP/HTTP-protobuf ``ExportMetricsServiceRequest`` body.

Persisted into ``external_metrics``; each normalized row is republished on the
``events`` pub/sub topic with envelope ``{"kind": "metric", ...}`` so the
dashboard can render Claude Code activity in real time.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from app.db import engine
from app.ingest.otel_metrics import (
    NormalizedExternalMetric,
    decode_otlp_metrics,
    normalize_metrics,
)
from app.realtime import BUS

_log = logging.getLogger("krakenops.routes.metrics_ingest")

router = APIRouter(prefix="/v1", tags=["external-metrics"])


@router.post("/metrics", status_code=status.HTTP_200_OK)
async def ingest_metrics(request: Request) -> dict[str, int]:
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")

    try:
        req = decode_otlp_metrics(body)
    except Exception as e:
        _log.warning("OTLP metrics decode failed: %s", e)
        raise HTTPException(400, f"invalid OTLP payload: {e}") from e

    payload = normalize_metrics(req)
    _persist(payload.metrics)

    # Fan-out happens AFTER commit so WS subscribers never see a metric the
    # /v1/events endpoint can't yet return.
    for m in payload.metrics:
        BUS.publish("events", _ws_envelope(m))

    return {"received": len(payload.metrics)}


# --- internals -----------------------------------------------------------


def _persist(metrics: list[NormalizedExternalMetric]) -> None:
    if not metrics:
        return
    with engine.begin() as conn:
        for m in metrics:
            conn.execute(
                text(
                    "INSERT INTO external_metrics"
                    " (service_name, metric_name, value, unit, attributes_json, ts_ns)"
                    " VALUES (:svc, :name, :val, :unit, :attrs, :ts)"
                ),
                {
                    "svc": m.service_name,
                    "name": m.metric_name,
                    "val": m.value,
                    "unit": m.unit,
                    "attrs": json.dumps(m.attributes, sort_keys=True, default=str),
                    "ts": m.ts_ns,
                },
            )


def _ws_envelope(m: NormalizedExternalMetric) -> dict[str, Any]:
    return {
        "kind": "metric",
        "service_name": m.service_name,
        "metric_name": m.metric_name,
        "value": m.value,
        "unit": m.unit,
        "attributes": m.attributes,
        "ts_ns": m.ts_ns,
    }
