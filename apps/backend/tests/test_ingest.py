"""OTLP decode + normalization, against the language-neutral fixtures."""

from __future__ import annotations

from app.ingest import decode_otlp, normalize
from tests._pb_builder import build_otlp_request


def test_minimal_fixture_normalizes(fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.minimal.json")
    body = build_otlp_request(fixture)
    payload = normalize(decode_otlp(body))

    assert payload.service_name == "tentacle-agent"
    assert len(payload.spans) == 2
    assert len(payload.token_usages) == 0  # no LLM data in this fixture

    by_name = {s.name: s for s in payload.spans}
    assert by_name["research"].tentacle_kind == "agent"
    assert by_name["research"].parent_span_id is None
    assert by_name["gather_notes"].tentacle_kind == "tool"
    assert by_name["gather_notes"].parent_span_id == by_name["research"].span_id


def test_with_tokens_fixture_extracts_usage(fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.with_tokens.json")
    body = build_otlp_request(fixture)
    payload = normalize(decode_otlp(body))

    assert len(payload.token_usages) == 1
    [usage] = payload.token_usages
    assert usage.gen_ai_system == "openai"
    assert usage.model == "gpt-4o-2024-08-06"
    assert usage.input_tokens == 412
    assert usage.output_tokens == 187


def test_human_review_fixture_marks_span(fixture_loader) -> None:
    fixture = fixture_loader("otel_spans.human_review.json")
    body = build_otlp_request(fixture)
    payload = normalize(decode_otlp(body))

    by_name = {s.name: s for s in payload.spans}
    review_span = by_name["confirm_source"]
    assert review_span.tentacle_kind == "human_review"
    assert review_span.needs_human_review is True
    assert review_span.status_code == "OK"
    # The custom event is preserved.
    [event] = review_span.events
    assert event["name"] == "tentacle.needs_human_review"
    assert "tentacle.review.prompt" in event["attributes"]


def test_decode_rejects_garbage() -> None:
    import pytest
    from google.protobuf.message import DecodeError

    with pytest.raises(DecodeError):
        decode_otlp(b"not a real protobuf")
