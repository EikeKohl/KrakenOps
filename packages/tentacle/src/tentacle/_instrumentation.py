"""Optional auto-instrumentation hooks for popular LLM SDKs.

Each hook is a no-op if the corresponding optional extra is not installed.
Errors during instrumentation are logged but never raised — a broken auto-
instrumentor must not break the user's agent loop.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("tentacle.instrumentation")


def _maybe_enable_openai() -> None:
    try:
        from opentelemetry.instrumentation.openai_v2 import (
            OpenAIInstrumentor,  # type: ignore[import-not-found]
        )
    except ImportError:
        _log.debug("openai auto-instrumentation skipped: extra not installed")
        return
    try:
        OpenAIInstrumentor().instrument()
        _log.info("openai auto-instrumentation enabled")
    except Exception as e:
        _log.warning("openai auto-instrumentation failed: %s", e)


def _maybe_enable_anthropic() -> None:
    try:
        from opentelemetry.instrumentation.anthropic import (
            AnthropicInstrumentor,  # type: ignore[import-not-found]
        )
    except ImportError:
        _log.debug("anthropic auto-instrumentation skipped: extra not installed")
        return
    try:
        AnthropicInstrumentor().instrument()
        _log.info("anthropic auto-instrumentation enabled")
    except Exception as e:
        _log.warning("anthropic auto-instrumentation failed: %s", e)
