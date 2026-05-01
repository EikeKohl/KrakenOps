"""Build OTLP/HTTP protobuf payloads from the language-neutral fixture JSON.

Same shape as `tests/contract/otel_spans.*.json`. Used by tests to drive the
`/v1/traces` ingest endpoint without needing to spin up a real `tentacle`
exporter. The same conversion the SDK does at runtime.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span as PbSpan


def build_otlp_request(fixture: dict[str, Any]) -> bytes:
    req = ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    for k, v in fixture["resource"]["attributes"].items():
        rs.resource.attributes.append(_kv(k, v))
    ss = rs.scope_spans.add()
    for span_dict in fixture["spans"]:
        pb = ss.spans.add()
        pb.trace_id = bytes.fromhex(span_dict["trace_id"])
        pb.span_id = bytes.fromhex(span_dict["span_id"])
        if span_dict.get("parent_span_id"):
            pb.parent_span_id = bytes.fromhex(span_dict["parent_span_id"])
        pb.name = span_dict["name"]
        pb.kind = PbSpan.SpanKind.Value(f"SPAN_KIND_{span_dict['kind']}")
        pb.start_time_unix_nano = span_dict["start_time_unix_nano"]
        pb.end_time_unix_nano = span_dict["end_time_unix_nano"]
        pb.status.code = type(pb.status).StatusCode.Value(
            f"STATUS_CODE_{span_dict['status']['code']}"
        )
        if span_dict["status"].get("message"):
            pb.status.message = span_dict["status"]["message"]
        for k, v in span_dict["attributes"].items():
            pb.attributes.append(_kv(k, v))
        for ev in span_dict.get("events", []):
            event = pb.events.add()
            event.name = ev["name"]
            event.time_unix_nano = ev["time_unix_nano"]
            for k, v in ev["attributes"].items():
                event.attributes.append(_kv(k, v))
    return req.SerializeToString()


def _kv(key: str, value: Any) -> KeyValue:
    kv = KeyValue()
    kv.key = key
    kv.value.CopyFrom(_any(value))
    return kv


def _any(value: Any) -> AnyValue:
    av = AnyValue()
    if isinstance(value, bool):
        av.bool_value = value
    elif isinstance(value, int):
        av.int_value = value
    elif isinstance(value, float):
        av.double_value = value
    elif isinstance(value, str):
        av.string_value = value
    elif isinstance(value, list):
        for item in value:
            av.array_value.values.append(_any(item))
    elif isinstance(value, dict):
        for k, v in value.items():
            kv = av.kvlist_value.values.add()
            kv.key = k
            kv.value.CopyFrom(_any(v))
    else:
        av.string_value = str(value)
    return av
