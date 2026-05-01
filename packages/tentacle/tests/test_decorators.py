"""Real assertions on the spans the decorators emit.

Each test grabs the InMemorySpanExporter via the `spans` fixture (see
conftest.py), runs decorated user code, then inspects the captured spans.
The schema asserted here matches ADR 0001.
"""

from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import tentacle


def test_track_agent_emits_one_span(spans: InMemorySpanExporter) -> None:
    @tentacle.track_agent
    def research(topic: str) -> str:
        return f"results for {topic}"

    out = research("krakenops")

    assert out == "results for krakenops"
    finished = spans.get_finished_spans()
    assert len(finished) == 1
    span = finished[0]
    assert span.name == "test_track_agent_emits_one_span.<locals>.research"
    assert span.attributes is not None
    assert span.attributes["tentacle.kind"] == "agent"
    assert span.attributes["tentacle.sdk.version"] == tentacle.__version__
    assert span.attributes["code.function"] == span.name
    assert span.status.status_code == StatusCode.UNSET


def test_tool_creates_child_of_agent(spans: InMemorySpanExporter) -> None:
    @tentacle.tool
    def gather(topic: str) -> list[str]:
        return [f"note about {topic}"]

    @tentacle.track_agent
    def research(topic: str) -> str:
        return ", ".join(gather(topic))

    research("ai")

    finished = spans.get_finished_spans()
    # Children finish before parents, so order is [gather, research].
    assert len(finished) == 2
    tool_span, agent_span = finished
    assert tool_span.attributes["tentacle.kind"] == "tool"
    assert agent_span.attributes["tentacle.kind"] == "agent"
    # Parent-child relationship by trace id + parent span id.
    assert tool_span.context.trace_id == agent_span.context.trace_id
    assert tool_span.parent is not None
    assert tool_span.parent.span_id == agent_span.context.span_id


async def test_async_agent_emits_span(spans: InMemorySpanExporter) -> None:
    @tentacle.track_agent
    async def research(topic: str) -> str:
        return f"async results for {topic}"

    out = await research("opentel")

    assert out == "async results for opentel"
    finished = spans.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].attributes["tentacle.kind"] == "agent"


def test_needs_human_review_marks_span(spans: InMemorySpanExporter) -> None:
    @tentacle.require_human
    def confirm(choice: str) -> str:
        raise tentacle.NeedsHumanReview(
            prompt="ambiguous source",
            payload={"options": ["a", "b"]},
        )

    with pytest.raises(tentacle.NeedsHumanReview):
        confirm("a")

    [span] = spans.get_finished_spans()
    assert span.attributes["tentacle.kind"] == "human_review"
    assert span.attributes["tentacle.needs_human_review"] is True
    # OK status — pause-for-human is a controlled signal, not a failure.
    assert span.status.status_code == StatusCode.OK
    # Event recorded with prompt + payload.
    [event] = span.events
    assert event.name == "tentacle.needs_human_review"
    assert event.attributes["tentacle.review.prompt"] == "ambiguous source"
    assert json.loads(event.attributes["tentacle.review.payload"]) == {"options": ["a", "b"]}


def test_arbitrary_exception_marks_error(spans: InMemorySpanExporter) -> None:
    @tentacle.tool
    def boom() -> None:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError):
        boom()

    [span] = spans.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    # OTel records the exception as an event named "exception".
    assert any(e.name == "exception" for e in span.events)


def test_oversized_review_payload_is_truncated(spans: InMemorySpanExporter) -> None:
    big = {"blob": "x" * 10_000}

    @tentacle.require_human
    def confirm() -> None:
        raise tentacle.NeedsHumanReview("too big", payload=big)

    with pytest.raises(tentacle.NeedsHumanReview):
        confirm()

    [span] = spans.get_finished_spans()
    [event] = span.events
    decoded = json.loads(event.attributes["tentacle.review.payload"])
    assert decoded == {"_truncated": True, "size": pytest.approx(decoded["size"])}


def test_unserializable_review_payload_is_handled(spans: InMemorySpanExporter) -> None:
    class Opaque:
        pass

    # `default=str` in _record_human_review handles this; payload becomes a string,
    # not _unserializable. We assert the call succeeds and an event is recorded.
    @tentacle.require_human
    def confirm() -> None:
        raise tentacle.NeedsHumanReview("opaque", payload={"obj": Opaque()})

    with pytest.raises(tentacle.NeedsHumanReview):
        confirm()

    [span] = spans.get_finished_spans()
    [event] = span.events
    assert event.attributes["tentacle.review.prompt"] == "opaque"
    # Payload is a JSON string of some kind — we don't pin its exact shape here.
    assert isinstance(event.attributes["tentacle.review.payload"], str)
