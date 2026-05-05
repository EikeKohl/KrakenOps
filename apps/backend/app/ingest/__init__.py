"""OTLP/HTTP decoders + normalizers.

- ``traces``        — span ingest from the ``tentacle`` SDK (ADR 0001).
- ``otel_metrics``  — external metrics (Claude Code) ingest (ADR 0005).
- ``otel_logs``     — external logs/events (Claude Code) ingest (ADR 0005).

The existing ``app.ingest.<symbol>`` callers (routes + tests) continue to work
because we re-export the trace symbols here.
"""

from app.ingest.traces import (
    NormalizedPayload,
    NormalizedSpan,
    NormalizedTokenUsage,
    decode_otlp,
    kv_attr_pairs,
    normalize,
    to_json,
)

__all__ = [
    "NormalizedPayload",
    "NormalizedSpan",
    "NormalizedTokenUsage",
    "decode_otlp",
    "kv_attr_pairs",
    "normalize",
    "to_json",
]
