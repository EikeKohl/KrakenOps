"""External OTLP logs/events ingest (ADR 0005)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from tests._pb_builder_external import build_logs_request


def test_post_logs_empty_body_400(client: TestClient) -> None:
    r = client.post("/v1/logs", content=b"")
    assert r.status_code == 400


def test_post_logs_garbage_400(client: TestClient) -> None:
    r = client.post(
        "/v1/logs",
        content=b"not a real protobuf",
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 400


def test_round_trip_persists_events_and_extracts_prompt_id(
    client: TestClient, fixture_loader
) -> None:
    fixture = fixture_loader("claude_code_logs.prompt_lifecycle.json")
    body = build_logs_request(fixture)

    r = client.post(
        "/v1/logs",
        content=body,
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 200
    assert r.json() == {"received": 3}

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT service_name, event_name, prompt_id, session_id,"
                " attributes_json, observed_at_ns"
                " FROM external_events ORDER BY id ASC"
            )
        ).all()

    assert len(rows) == 3
    assert {r[0] for r in rows} == {"claude-code"}

    event_names = {r[1] for r in rows}
    assert event_names == {
        "claude_code.user_prompt",
        "claude_code.api_request",
        "claude_code.tool_result",
    }

    # All three records share the same prompt — ADR 0005 §"Negative / accepted
    # risks" promises that prompt.id lands in its own indexed column.
    prompt_ids = {r[2] for r in rows}
    assert prompt_ids == {"01HV2T9C8RE7PYM4WQH3K0YN2K"}

    # Session id likewise pulled out.
    session_ids = {r[3] for r in rows}
    assert session_ids == {"01HV2T8WJ9KX1S5N4ZGXN8MZP3"}

    # The api_request event's full attribute payload survives in JSON.
    api_row = next(r for r in rows if r[1] == "claude_code.api_request")
    api_attrs = json.loads(api_row[4])
    assert api_attrs["model"] == "claude-opus-4-7"
    assert api_attrs["input_tokens"] == 1842
    assert api_attrs["output_tokens"] == 287

    # observed_at_ns preserved for the user_prompt record.
    user_row = next(r for r in rows if r[1] == "claude_code.user_prompt")
    assert int(user_row[5]) == 1746374410000000000


def test_logs_publishes_on_events_topic(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("claude_code_logs.prompt_lifecycle.json")
    body = build_logs_request(fixture)

    with client.websocket_connect("/v1/ws?topics=events") as ws:
        r = client.post(
            "/v1/logs",
            content=body,
            headers={"Content-Type": "application/x-protobuf"},
        )
        assert r.status_code == 200

        seen = [ws.receive_json() for _ in range(3)]

    assert all(m["topic"] == "events" for m in seen)
    assert all(m["data"]["kind"] == "event" for m in seen)
    assert all(m["data"]["service_name"] == "claude-code" for m in seen)
    assert all(
        m["data"]["prompt_id"] == "01HV2T9C8RE7PYM4WQH3K0YN2K" for m in seen
    )


def test_get_events_filters_by_service_and_since(
    client: TestClient, fixture_loader
) -> None:
    fixture = fixture_loader("claude_code_logs.prompt_lifecycle.json")
    body = build_logs_request(fixture)
    client.post(
        "/v1/logs",
        content=body,
        headers={"Content-Type": "application/x-protobuf"},
    )

    # No filters — all three records.
    listing = client.get("/v1/events").json()
    assert len(listing["events"]) == 3
    assert all(e["service_name"] == "claude-code" for e in listing["events"])
    # Sorted DESC.
    timestamps = [e["observed_at_ns"] for e in listing["events"]]
    assert timestamps == sorted(timestamps, reverse=True)

    # `since` filter excludes the earliest record (user_prompt @ 1746374410…).
    since = 1746374411_000_000_000
    filtered = client.get("/v1/events", params={"since": since}).json()
    assert len(filtered["events"]) == 2
    assert all(e["observed_at_ns"] >= since for e in filtered["events"])

    # Unknown service → empty.
    empty = client.get("/v1/events", params={"service": "nothing"}).json()
    assert empty["events"] == []
