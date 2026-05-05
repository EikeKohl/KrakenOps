"""OTLP/HTTP metrics decoder (ADR 0005).

External tools (Claude Code is the v1 target) emit OTLP metrics over HTTP/protobuf
to ``POST /v1/metrics``. This module decodes those bytes into a flat list of
:class:`NormalizedExternalMetric` rows that the route persists into
``external_metrics`` and re-publishes on the ``events`` WS topic.

We handle the two instrument types Claude Code emits — ``Sum`` (counter) and
``Gauge``. Histograms are explicitly out of scope for v1: we warn once per
metric name and skip them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import Metric, NumberDataPoint

_log = logging.getLogger("krakenops.ingest.otel_metrics")

# Names we have already warned about for unsupported instrument types — keeps
# log noise bounded if a histogram is sent every few seconds.
_HISTOGRAM_WARNED: set[str] = set()


@dataclass
class NormalizedExternalMetric:
    service_name: str
    metric_name: str
    value: float
    unit: str | None
    attributes: dict[str, Any]
    ts_ns: int


@dataclass
class NormalizedMetricPayload:
    service_name: str
    metrics: list[NormalizedExternalMetric] = field(default_factory=list)


def decode_otlp_metrics(body: bytes) -> ExportMetricsServiceRequest:
    req = ExportMetricsServiceRequest()
    req.ParseFromString(body)
    return req


def normalize_metrics(req: ExportMetricsServiceRequest) -> NormalizedMetricPayload:
    """Walk resource_metrics → scope_metrics → metrics → data_points."""
    out: list[NormalizedExternalMetric] = []
    service_name = "unknown"

    for resource_metrics in req.resource_metrics:
        resource_attrs = _kv_to_dict(resource_metrics.resource.attributes)
        rm_service_name = str(resource_attrs.get("service.name", "")) or "unknown"
        # Last-writer-wins is fine — Claude Code only ever sets one resource per export.
        service_name = rm_service_name

        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                out.extend(_normalize_metric(metric, rm_service_name))

    return NormalizedMetricPayload(service_name=service_name, metrics=out)


# --- internals -----------------------------------------------------------


def _normalize_metric(metric: Metric, service_name: str) -> list[NormalizedExternalMetric]:
    kind = metric.WhichOneof("data")
    unit = metric.unit or None

    if kind == "sum":
        return [
            _from_number_point(metric.name, unit, dp, service_name)
            for dp in metric.sum.data_points
        ]
    if kind == "gauge":
        return [
            _from_number_point(metric.name, unit, dp, service_name)
            for dp in metric.gauge.data_points
        ]
    if kind in ("histogram", "exponential_histogram", "summary"):
        if metric.name not in _HISTOGRAM_WARNED:
            _HISTOGRAM_WARNED.add(metric.name)
            _log.warning(
                "ignoring unsupported metric instrument %r for %r (v1 supports sum/gauge only)",
                kind,
                metric.name,
            )
        return []
    # Unknown / not set — silent skip.
    return []


def _from_number_point(
    name: str,
    unit: str | None,
    dp: NumberDataPoint,
    service_name: str,
) -> NormalizedExternalMetric:
    value_field = dp.WhichOneof("value")
    if value_field == "as_int":
        value = float(dp.as_int)
    elif value_field == "as_double":
        value = float(dp.as_double)
    else:
        value = 0.0
    return NormalizedExternalMetric(
        service_name=service_name,
        metric_name=name,
        value=value,
        unit=unit,
        attributes=_kv_to_dict(dp.attributes),
        ts_ns=int(dp.time_unix_nano),
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
