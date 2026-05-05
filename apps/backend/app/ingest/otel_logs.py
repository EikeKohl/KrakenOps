"""OTLP/HTTP logs decoder (ADR 0005).

Claude Code emits structured log records (the modern OTel "events" pattern:
``log_record.event_name`` set, body usually empty) over HTTP/protobuf.
This module decodes those bytes into a list of
:class:`NormalizedExternalEvent` rows for ``external_events`` storage and
``events`` WS broadcast.

ADR 0005 §"Negative / accepted risks" — we special-case ``prompt.id`` and
``session.id`` into indexed columns. Other attributes land in
``attributes_json`` (and the originals are still preserved there too).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue

_log = logging.getLogger("krakenops.ingest.otel_logs")


@dataclass
class NormalizedExternalEvent:
    service_name: str
    event_name: str
    prompt_id: str | None
    session_id: str | None
    attributes: dict[str, Any]
    observed_at_ns: int


@dataclass
class NormalizedLogPayload:
    service_name: str
    events: list[NormalizedExternalEvent] = field(default_factory=list)


def decode_otlp_logs(body: bytes) -> ExportLogsServiceRequest:
    req = ExportLogsServiceRequest()
    req.ParseFromString(body)
    return req


def normalize_logs(req: ExportLogsServiceRequest) -> NormalizedLogPayload:
    """Walk resource_logs → scope_logs → log_records."""
    out: list[NormalizedExternalEvent] = []
    service_name = "unknown"

    for resource_logs in req.resource_logs:
        resource_attrs = _kv_to_dict(resource_logs.resource.attributes)
        rl_service_name = str(resource_attrs.get("service.name", "")) or "unknown"
        service_name = rl_service_name

        for scope_logs in resource_logs.scope_logs:
            for record in scope_logs.log_records:
                event = _normalize_record(record, rl_service_name)
                if event is not None:
                    out.append(event)

    return NormalizedLogPayload(service_name=service_name, events=out)


# --- internals -----------------------------------------------------------


def _normalize_record(record: Any, service_name: str) -> NormalizedExternalEvent | None:
    attrs = _kv_to_dict(record.attributes)

    # Prefer the modern OTel logs/events `event_name` field. Fall back to the
    # `event.name` attribute that older log records use for the same purpose.
    event_name = record.event_name or str(attrs.get("event.name") or "")
    if not event_name:
        # A record with no event name isn't useful to us — drop it. (We don't
        # store free-form log lines; we want structured events only.)
        return None

    prompt_id = attrs.get("prompt.id")
    session_id = attrs.get("session.id")

    observed_at = int(record.observed_time_unix_nano or record.time_unix_nano or 0)

    return NormalizedExternalEvent(
        service_name=service_name,
        event_name=event_name,
        prompt_id=str(prompt_id) if prompt_id is not None else None,
        session_id=str(session_id) if session_id is not None else None,
        attributes=attrs,
        observed_at_ns=observed_at,
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
