"""HTTP route tests: ingest + list + cost rollup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests._pb_builder import build_otlp_request


def test_post_traces_empty_body_400(client: TestClient) -> None:
    response = client.post("/v1/traces", content=b"")
    assert response.status_code == 400


def test_post_traces_garbage_400(client: TestClient) -> None:
    response = client.post(
        "/v1/traces",
        content=b"not a real protobuf",
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert response.status_code == 400


def test_full_round_trip_minimal(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.minimal.json")
    body = build_otlp_request(fixture)

    r = client.post(
        "/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"}
    )
    assert r.status_code == 200

    # GET /v1/traces — find the inserted trace.
    listing = client.get("/v1/traces").json()
    assert listing["traces"]
    trace_id = fixture["spans"][0]["trace_id"]
    matched = next((t for t in listing["traces"] if t["trace_id"] == trace_id), None)
    assert matched is not None
    assert matched["span_count"] == 2
    assert matched["service_name"] == "tentacle-agent"
    assert matched["has_human_review"] is False

    # GET /v1/traces/{id} — full span tree.
    detail = client.get(f"/v1/traces/{trace_id}").json()
    assert len(detail["spans"]) == 2
    span_kinds = {s["tentacle_kind"] for s in detail["spans"]}
    assert span_kinds == {"agent", "tool"}


def test_round_trip_with_tokens_computes_cost(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.with_tokens.json")
    body = build_otlp_request(fixture)
    r = client.post(
        "/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"}
    )
    assert r.status_code == 200

    trace_id = fixture["spans"][0]["trace_id"]
    detail = client.get(f"/v1/traces/{trace_id}").json()
    llm_spans = [s for s in detail["spans"] if "token_usage" in s]
    assert len(llm_spans) == 1
    usage = llm_spans[0]["token_usage"]
    assert usage["model"] == "gpt-4o-2024-08-06"
    # 412 input * $0.0025/1k + 187 output * $0.0100/1k
    expected = round((412 / 1000) * 0.0025 + (187 / 1000) * 0.0100, 8)
    assert usage["cost_usd"] == expected


def test_round_trip_human_review(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.human_review.json")
    body = build_otlp_request(fixture)
    client.post("/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"})

    listing = client.get("/v1/traces").json()
    trace_id = fixture["spans"][0]["trace_id"]
    matched = next(t for t in listing["traces"] if t["trace_id"] == trace_id)
    assert matched["has_human_review"] is True


def test_get_spans_filtered_by_kind(client: TestClient, fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.minimal.json")
    body = build_otlp_request(fixture)
    client.post("/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"})

    only_tools = client.get("/v1/spans", params={"kind": "tool"}).json()
    assert all(s["tentacle_kind"] == "tool" for s in only_tools["spans"])
    assert any(s["name"] == "gather_notes" for s in only_tools["spans"])

    only_agents = client.get("/v1/spans", params={"kind": "agent"}).json()
    assert all(s["tentacle_kind"] == "agent" for s in only_agents["spans"])


def test_costs_rollup(client: TestClient, fixture_loader) -> None:
    # Bring fixture timestamps into the current 24h window — the canonical
    # fixtures use frozen 2024 timestamps for stability.
    fixture = fixture_loader("otel_spans.with_tokens.json")
    import time as _t

    now_ns = _t.time_ns()
    for i, span in enumerate(fixture["spans"]):
        span["start_time_unix_nano"] = now_ns - (10 - i) * 1_000_000_000
        span["end_time_unix_nano"] = now_ns - (5 - i) * 1_000_000_000

    body = build_otlp_request(fixture)
    client.post("/v1/traces", content=body, headers={"Content-Type": "application/x-protobuf"})

    rollup = client.get("/v1/costs", params={"window": "24h"}).json()
    assert rollup["window"] == "24h"
    assert any(m["model"] == "gpt-4o-2024-08-06" for m in rollup["by_model"])
    assert rollup["total_cost_usd"] > 0


def test_costs_rejects_bad_window(client: TestClient) -> None:
    r = client.get("/v1/costs", params={"window": "bogus"})
    assert r.status_code == 400


def test_get_unknown_trace_404(client: TestClient) -> None:
    r = client.get("/v1/traces/" + "0" * 32)
    assert r.status_code == 404
