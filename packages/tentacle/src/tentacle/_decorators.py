"""Decorator implementations for @track_agent, @tool, @require_human.

All three share the same span lifecycle, differing only in the `tentacle.kind`
attribute. Sync and async user functions are both supported. See ADR 0001 for
the span schema this module emits.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from functools import wraps
from typing import Any, Literal, TypeVar

from tentacle._core import _get_tracer
from tentacle._exceptions import NeedsHumanReview
from tentacle._version import __version__

F = TypeVar("F", bound=Callable[..., Any])

Kind = Literal["agent", "tool", "human_review"]

# Cap NeedsHumanReview payload to keep span events bounded; ADR 0001.
_PAYLOAD_BYTE_CAP = 4096


def _set_base_attrs(span: Any, func: Callable[..., Any], kind: Kind) -> None:
    span.set_attribute("tentacle.kind", kind)
    span.set_attribute("tentacle.sdk.version", __version__)
    span.set_attribute("code.function", func.__qualname__)
    span.set_attribute("code.namespace", getattr(func, "__module__", "") or "")


def _record_human_review(span: Any, exc: NeedsHumanReview) -> None:
    span.set_attribute("tentacle.needs_human_review", True)
    try:
        payload_json = json.dumps(exc.payload, default=str)
    except (TypeError, ValueError):
        payload_json = json.dumps({"_unserializable": True})
    if len(payload_json.encode("utf-8")) > _PAYLOAD_BYTE_CAP:
        payload_json = json.dumps({"_truncated": True, "size": len(payload_json)})
    span.add_event(
        "tentacle.needs_human_review",
        attributes={
            "tentacle.review.prompt": exc.prompt,
            "tentacle.review.payload": payload_json,
        },
    )
    # Pause-for-human is a controlled signal, not a failure.
    from opentelemetry.trace import Status, StatusCode

    span.set_status(Status(StatusCode.OK))


def _record_error(span: Any, exc: BaseException) -> None:
    from opentelemetry.trace import Status, StatusCode

    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


def _wrap(func: F, *, kind: Kind) -> F:
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = _get_tracer()
            with tracer.start_as_current_span(
                func.__qualname__,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                _set_base_attrs(span, func, kind)
                try:
                    return await func(*args, **kwargs)
                except NeedsHumanReview as e:
                    _record_human_review(span, e)
                    raise
                except BaseException as e:
                    _record_error(span, e)
                    raise

        return async_wrapper  # type: ignore[return-value]

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = _get_tracer()
        with tracer.start_as_current_span(
            func.__qualname__,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            _set_base_attrs(span, func, kind)
            try:
                return func(*args, **kwargs)
            except NeedsHumanReview as e:
                _record_human_review(span, e)
                raise
            except BaseException as e:
                _record_error(span, e)
                raise

    return sync_wrapper  # type: ignore[return-value]


def track_agent(func: F) -> F:
    """Mark a function as the entry point of an agent run."""
    return _wrap(func, kind="agent")


def tool(func: F) -> F:
    """Mark a function as a tool call within an agent run."""
    return _wrap(func, kind="tool")


def require_human(func: F) -> F:
    """Mark a function as a human-review gate.

    Functionally identical to @tool today; the distinct kind lets the dashboard
    render these spans differently and lets users grep traces for them.
    """
    return _wrap(func, kind="human_review")
