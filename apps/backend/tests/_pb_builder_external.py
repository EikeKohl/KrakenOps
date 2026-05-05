"""Build OTLP/HTTP protobuf bodies for the external-OTel ingest tests (ADR 0005).

The fixtures live in `tests/contract/claude_code_*.json` and describe the
*decoded* shape of an `ExportMetricsServiceRequest` / `ExportLogsServiceRequest`
the way the backend would see it after parsing the wire bytes. These helpers
go the other direction — JSON → protobuf bytes — so the tests can hit the
REST endpoints with the same shape Claude Code would produce.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue


def build_metrics_request(fixture: dict[str, Any]) -> bytes:
    req = ExportMetricsServiceRequest()
    rm = req.resource_metrics.add()
    for k, v in fixture["resource"]["attributes"].items():
        rm.resource.attributes.append(_kv(k, v))

    sm = rm.scope_metrics.add()
    for metric_dict in fixture["metrics"]:
        m = sm.metrics.add()
        m.name = metric_dict["name"]
        if metric_dict.get("unit"):
            m.unit = metric_dict["unit"]

        instrument = metric_dict.get("instrument", "counter")
        if instrument in ("counter", "sum"):
            container = m.sum.data_points
            # AGGREGATION_TEMPORALITY_CUMULATIVE = 2 (Claude Code default)
            m.sum.aggregation_temporality = 2
            m.sum.is_monotonic = True
        elif instrument == "gauge":
            container = m.gauge.data_points
        else:
            raise ValueError(f"unsupported test instrument: {instrument!r}")

        for dp in metric_dict["data_points"]:
            point = container.add()
            value = dp["value"]
            if isinstance(value, bool):  # bools first — bool is a subclass of int
                point.as_int = int(value)
            elif isinstance(value, int):
                point.as_int = value
            else:
                point.as_double = float(value)
            point.time_unix_nano = int(dp["time_unix_nano"])
            for k, v in dp.get("attributes", {}).items():
                point.attributes.append(_kv(k, v))
    return req.SerializeToString()


def build_logs_request(fixture: dict[str, Any]) -> bytes:
    req = ExportLogsServiceRequest()
    rl = req.resource_logs.add()
    for k, v in fixture["resource"]["attributes"].items():
        rl.resource.attributes.append(_kv(k, v))

    sl = rl.scope_logs.add()
    for log_dict in fixture["logs"]:
        record = sl.log_records.add()
        if log_dict.get("event_name"):
            record.event_name = log_dict["event_name"]
        if "observed_time_unix_nano" in log_dict:
            record.observed_time_unix_nano = int(log_dict["observed_time_unix_nano"])
        if "time_unix_nano" in log_dict:
            record.time_unix_nano = int(log_dict["time_unix_nano"])
        if log_dict.get("severity_text"):
            record.severity_text = log_dict["severity_text"]
        for k, v in (log_dict.get("attributes") or {}).items():
            record.attributes.append(_kv(k, v))
    return req.SerializeToString()


# --- helpers shared with _pb_builder.py (kept private here to avoid a cross-import) ----


def _kv(key: str, value: Any) -> KeyValue:
    kv = KeyValue()
    kv.key = key
    kv.value.CopyFrom(_any(value))
    return kv


def _any(value: Any) -> AnyValue:
    av = AnyValue()
    if value is None:
        # OTel has no native "null" — drop it on the floor as an empty AnyValue.
        return av
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
