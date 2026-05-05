"""SDK lifecycle: init(), tracer accessor, idempotency state.

`init()` is intentionally idempotent: calling it more than once is a no-op
after the first call (additional kwargs are ignored with a warning). Decorators
work without `init()` having been called — they will simply create spans
against OTel's default no-op tracer provider, so user code keeps running.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from tentacle._version import __version__

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

_log = logging.getLogger("tentacle")
_lock = threading.Lock()
_initialized = False
_TRACER_NAME = "tentacle"

DEFAULT_ENDPOINT = "http://localhost:8787/v1/traces"


def init(
    endpoint: str | None = None,
    service_name: str = "tentacle-agent",
    headers: dict[str, str] | None = None,
    enable_openai: bool = True,
    enable_anthropic: bool = True,
    resource_attributes: dict[str, str] | None = None,
) -> None:
    """Configure the OpenTelemetry pipeline for `tentacle`.

    Idempotent: only the first call has effect. Subsequent calls are silently ignored.

    Parameters
    ----------
    endpoint:
        OTLP/HTTP traces endpoint. If omitted, reads ``TENTACLE_ENDPOINT`` from
        the environment, falling back to ``http://localhost:8787/v1/traces``.
    service_name:
        Sets the OTel ``service.name`` resource attribute. Surfaces as the agent
        name in the KrakenOps dashboard.
    headers:
        Extra HTTP headers to send with each export (e.g. for hosted backends).
    enable_openai, enable_anthropic:
        If the corresponding optional extra is installed, attempt to enable
        auto-instrumentation. Silent no-op if the package isn't present.
    resource_attributes:
        Extra OTel resource attributes merged into the default set.
    """
    global _initialized

    with _lock:
        if _initialized:
            _log.debug("tentacle.init() called more than once; ignoring.")
            return

        # Lazy import: keep import-time side effects minimal so users who only
        # decorate without calling init() don't pay for the SDK setup.
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        ep = endpoint or os.environ.get("TENTACLE_ENDPOINT") or DEFAULT_ENDPOINT

        attrs = {
            "service.name": service_name,
            "telemetry.sdk.name": "tentacle",
            "telemetry.sdk.version": __version__,
        }
        if resource_attributes:
            attrs.update(resource_attributes)

        provider = TracerProvider(resource=Resource.create(attrs))
        exporter = OTLPSpanExporter(endpoint=ep, headers=headers or {})
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        if enable_openai:
            from tentacle._instrumentation import _maybe_enable_openai

            _maybe_enable_openai()
        if enable_anthropic:
            from tentacle._instrumentation import _maybe_enable_anthropic

            _maybe_enable_anthropic()

        # ADR 0008 — share the host:port with the status helpers so
        # tentacle.claim_ticket / set_status / set_todos can POST without
        # a second config call.
        from tentacle import _status

        _status._set_api_base(ep)

        _initialized = True
        _log.info("tentacle initialized: endpoint=%s service=%s", ep, service_name)


def _get_tracer() -> Tracer:
    """Return the tentacle tracer. Works whether or not init() was called."""
    from opentelemetry import trace

    return trace.get_tracer(_TRACER_NAME, __version__)


def _is_initialized() -> bool:
    return _initialized


def _reset_for_tests() -> None:
    """Test-only: clear state so a subsequent init() runs fresh.

    Not part of the public API; tests import from tentacle._core directly.
    """
    global _initialized
    with _lock:
        _initialized = False
