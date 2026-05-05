"""External OTLP metrics ingest (ADR 0005).

Replays the language-neutral fixture in tests/contract/, builds an
ExportMetricsServiceRequest in-memory, POSTs it through the TestClient,
and asserts on storage + WS fan-out.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from tests._pb_builder_external import build_metrics_request


def test_post_metrics_empty_body_400(client: TestClient) -> None:
    r = client.post("/v1/metrics", content=b"")
    assert r.status_code == 400


def test_post_metrics_garbage_400(client: TestClient) -> None:
    r = client.post(
        "/v1/metrics",
        content=b"not a real protobuf",
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 400


def test_round_trip_persists_rows(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("claude_code_metrics.minimal.json")
    body = build_metrics_request(fixture)

    r = client.post(
        "/v1/metrics",
        content=body,
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 200
    # The minimal fixture has 1 + 2 + 1 = 4 data points across 3 metrics.
    assert r.json() == {"received": 4}

    # Storage check.
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT service_name, metric_name, value, unit, attributes_json, ts_ns"
                " FROM external_metrics ORDER BY id ASC"
            )
        ).all()
    assert len(rows) == 4
    # All rows belong to claude-code per the fixture's resource.attributes.
    assert {row[0] for row in rows} == {"claude-code"}

    # The token.usage counter has two data points: input=1842, output=287.
    token_rows = [row for row in rows if row[1] == "claude_code.token.usage"]
    assert {int(row[2]) for row in token_rows} == {1842, 287}
    # Unit preserved.
    assert {row[3] for row in token_rows} == {"{token}"}
    # Attributes survive round-trip via JSON column.
    attrs_for_input = next(
        json.loads(row[4]) for row in token_rows if int(row[2]) == 1842
    )
    assert attrs_for_input["type"] == "input"
    assert attrs_for_input["model"] == "claude-opus-4-7"

    # Cost row stored as float.
    cost_rows = [row for row in rows if row[1] == "claude_code.cost.usage"]
    assert len(cost_rows) == 1
    assert cost_rows[0][2] == pytest.approx(0.0489)
    assert cost_rows[0][3] == "USD"

    # ts_ns preserved.
    session_row = next(row for row in rows if row[1] == "claude_code.session.count")
    assert int(session_row[5]) == 1746374400000000000


def test_metrics_publishes_on_events_topic(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("claude_code_metrics.minimal.json")
    body = build_metrics_request(fixture)

    with client.websocket_connect("/v1/ws?topics=events") as ws:
        r = client.post(
            "/v1/metrics",
            content=body,
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert r.status_code == 200

        # 4 data points → 4 envelopes.
        seen = [ws.receive_json() for _ in range(4)]

    assert all(m["topic"] == "events" for m in seen)
    assert all(m["data"]["kind"] == "metric" for m in seen)
    assert all(m["data"]["service_name"] == "claude-code" for m in seen)
    metric_names = {m["data"]["metric_name"] for m in seen}
    assert metric_names == {
        "claude_code.session.count",
        "claude_code.token.usage",
        "claude_code.cost.usage",
    }
    # Attributes ride along on the envelope.
    token_envelope = next(
        m for m in seen
        if m["data"]["metric_name"] == "claude_code.token.usage"
        and m["data"]["attributes"].get("type") == "input"
    )
    assert token_envelope["data"]["value"] == pytest.approx(1842)


def test_histogram_metrics_are_skipped_warn_once(client: TestClient) -> None:
    """Histograms aren't supported in v1 — they must be silently skipped, not 500."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest,
    )
    from opentelemetry.proto.common.v1.common_pb2 import KeyValue

    req = ExportMetricsServiceRequest()
    rm = req.resource_metrics.add()
    kv = KeyValue()
    kv.key = "service.name"
    kv.value.string_value = "claude-code"
    rm.resource.attributes.append(kv)
    sm = rm.scope_metrics.add()
    h = sm.metrics.add()
    h.name = "claude_code.something.histogram"
    h.unit = "ms"
    dp = h.histogram.data_points.add()
    dp.time_unix_nano = 1_000_000_000_000
    dp.count = 5
    dp.sum = 12.5

    r = client.post(
        "/v1/metrics",
        content=req.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 200
    assert r.json() == {"received": 0}
