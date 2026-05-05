"""Realtime: WS subscribe/receive + POST /v1/traces fan-out."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests._pb_builder import build_otlp_request


def test_ws_rejects_invalid_topics(client: TestClient) -> None:
    # All topics invalid → server closes immediately. Starlette's TestClient
    # raises WebSocketDisconnect on the first receive in that case.
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/v1/ws?topics=bogus") as ws,
    ):
        ws.receive_text()


def test_ws_metrics_topic_receives_sample(client: TestClient) -> None:
    # The lifespan started the sampler at 1Hz; one metric should arrive within ~1.5s.
    with client.websocket_connect("/v1/ws?topics=metrics") as ws:
        msg = ws.receive_json()
    assert msg["topic"] == "metrics"
    assert {"cpu_pct", "ram_pct", "disk_pct", "ts_ns"} <= msg["data"].keys()


def test_ws_traces_topic_fanned_out_on_post(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.minimal.json")
    body = build_otlp_request(fixture)

    with client.websocket_connect("/v1/ws?topics=traces") as ws:
        # POST happens while WS is connected; the route publishes synchronously
        # so subscribers see messages by the time the response returns.
        r = client.post(
            "/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"}
        )
        assert r.status_code == 200

        seen: list[dict] = []
        for _ in range(2):
            msg = ws.receive_json()
            seen.append(msg)

    assert all(m["topic"] == "traces" for m in seen)
    names = {m["data"]["name"] for m in seen}
    assert names == {"research", "gather_notes"}
    # Compact summary shape, not the full attributes dump.
    sample = seen[0]["data"]
    assert "tentacle_kind" in sample
    assert "service_name" in sample
    assert "attributes" not in sample  # full attrs come via REST


def test_ws_default_topics_is_all_known(client: TestClient) -> None:
    # No `?topics=` → default to all topics; the hardware sampler ensures we
    # receive a metrics ping promptly even with no traces being posted.
    from app.realtime.bus import TOPICS

    with client.websocket_connect("/v1/ws") as ws:
        msg = ws.receive_json()
    assert msg["topic"] in set(TOPICS)
