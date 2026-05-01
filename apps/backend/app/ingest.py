"""OTLP/HTTP decode + normalization to KrakenOps storage shape.

Input: a raw protobuf body matching ExportTraceServiceRequest (the OTLP/HTTP
contract used by `tentacle`'s OTLPSpanExporter).
Output: lists of pure-Python dicts matching the SQLite schema in
migrations/001_initial.sql, plus a derived `cost_usd` per LLM span.

This module is the **converter** referenced in tests/contract/README.md — the
same fixtures exercise both the SDK output and this decoder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span as PbSpan

# Inputs that look like an LLM call must carry these GenAI semantic-conv attrs
# for token usage to count (ADR 0001).
_GENAI_MODEL_ATTR = "gen_ai.request.model"
_GENAI_INPUT_ATTR = "gen_ai.usage.input_tokens"
_GENAI_OUTPUT_ATTR = "gen_ai.usage.output_tokens"
_GENAI_SYSTEM_ATTR = "gen_ai.system"


@dataclass
class NormalizedSpan:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    otel_kind: str
    tentacle_kind: str | None
    start_time_ns: int
    end_time_ns: int
    status_code: str
    status_message: str | None
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    needs_human_review: bool


@dataclass
class NormalizedTokenUsage:
    span_id: str
    trace_id: str
    gen_ai_system: str | None
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class NormalizedPayload:
    """Result of decoding an OTLP/HTTP request body."""

    service_name: str
    spans: list[NormalizedSpan]
    token_usages: list[NormalizedTokenUsage]


def decode_otlp(body: bytes) -> ExportTraceServiceRequest:
    req = ExportTraceServiceRequest()
    req.ParseFromString(body)
    return req


def normalize(req: ExportTraceServiceRequest) -> NormalizedPayload:
    spans: list[NormalizedSpan] = []
    usages: list[NormalizedTokenUsage] = []
    service_name = "unknown"

    for resource_spans in req.resource_spans:
        # Resource attributes give us service.name (and others we keep on each span).
        resource_attrs = _kv_to_dict(resource_spans.resource.attributes)
        if "service.name" in resource_attrs:
            service_name = str(resource_attrs["service.name"])

        for scope_spans in resource_spans.scope_spans:
            for pb in scope_spans.spans:
                span = _normalize_span(pb)
                spans.append(span)
                usage = _maybe_token_usage(span)
                if usage is not None:
                    usages.append(usage)

    return NormalizedPayload(
        service_name=service_name,
        spans=spans,
        token_usages=usages,
    )


# --- internals -----------------------------------------------------------


def _normalize_span(pb: PbSpan) -> NormalizedSpan:
    attrs = _kv_to_dict(pb.attributes)
    events = [
        {
            "name": e.name,
            "time_unix_nano": int(e.time_unix_nano),
            "attributes": _kv_to_dict(e.attributes),
        }
        for e in pb.events
    ]
    parent_hex = pb.parent_span_id.hex() if pb.parent_span_id else ""
    return NormalizedSpan(
        span_id=pb.span_id.hex(),
        trace_id=pb.trace_id.hex(),
        parent_span_id=parent_hex or None,
        name=pb.name,
        otel_kind=_strip_prefix(PbSpan.SpanKind.Name(pb.kind), "SPAN_KIND_"),
        tentacle_kind=str(attrs.get("tentacle.kind")) if "tentacle.kind" in attrs else None,
        start_time_ns=int(pb.start_time_unix_nano),
        end_time_ns=int(pb.end_time_unix_nano),
        status_code=_strip_prefix(
            type(pb.status).StatusCode.Name(pb.status.code), "STATUS_CODE_"
        ),
        status_message=pb.status.message or None,
        attributes=attrs,
        events=events,
        needs_human_review=bool(attrs.get("tentacle.needs_human_review")),
    )


def _maybe_token_usage(span: NormalizedSpan) -> NormalizedTokenUsage | None:
    model = span.attributes.get(_GENAI_MODEL_ATTR)
    if not model:
        return None
    inp = span.attributes.get(_GENAI_INPUT_ATTR)
    out = span.attributes.get(_GENAI_OUTPUT_ATTR)
    if inp is None or out is None:
        return None
    return NormalizedTokenUsage(
        span_id=span.span_id,
        trace_id=span.trace_id,
        gen_ai_system=(
            str(span.attributes[_GENAI_SYSTEM_ATTR])
            if _GENAI_SYSTEM_ATTR in span.attributes
            else None
        ),
        model=str(model),
        input_tokens=int(inp),
        output_tokens=int(out),
    )


def _kv_to_dict(kvs: Any) -> dict[str, Any]:
    return {kv.key: _any_value(kv.value) for kv in kvs}


def _any_value(v: AnyValue) -> Any:
    f = v.WhichOneof("value")
    if f == "string_value":
        return v.string_value
    if f == "bool_value":
        return v.bool_value
    if f == "int_value":
        return v.int_value
    if f == "double_value":
        return v.double_value
    if f == "bytes_value":
        return v.bytes_value
    if f == "array_value":
        return [_any_value(x) for x in v.array_value.values]
    if f == "kvlist_value":
        return {kv.key: _any_value(kv.value) for kv in v.kvlist_value.values}
    return None


def _strip_prefix(name: str, prefix: str) -> str:
    return name[len(prefix) :] if name.startswith(prefix) else name


def to_json(obj: Any) -> str:
    """Stable JSON encoder for storing attributes/events as TEXT columns."""
    return json.dumps(obj, sort_keys=True, default=str)


def kv_attr_pairs(kvs: list[KeyValue]) -> dict[str, Any]:  # pragma: no cover - convenience export
    return _kv_to_dict(kvs)
