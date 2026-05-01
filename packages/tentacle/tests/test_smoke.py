"""Smoke tests: imports work, decorators are callable, exception is raisable.

These are the lowest-bar guarantees — the real span-shape assertions live in
test_decorators.py. Smoke tests intentionally do NOT use the spans fixture;
they exercise the decorators against the default no-op tracer to prove that
user code keeps working even when init() has not been called.
"""

from __future__ import annotations

import pytest

import tentacle


def test_version_is_string() -> None:
    assert isinstance(tentacle.__version__, str)
    assert tentacle.__version__.count(".") == 2


def test_init_is_callable_and_idempotent() -> None:
    # First call uses a fake endpoint; second call must be a no-op.
    tentacle.init(endpoint="http://localhost:1/__nowhere__")
    tentacle.init(endpoint="http://localhost:1/__nowhere2__")


def test_track_agent_passes_through_without_init() -> None:
    @tentacle.track_agent
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_tool_passes_through_without_init() -> None:
    @tentacle.tool
    def shout(s: str) -> str:
        return s.upper()

    assert shout("ok") == "OK"


def test_require_human_passes_through_without_init() -> None:
    @tentacle.require_human
    def maybe_pause(x: int) -> int:
        return x * 2

    assert maybe_pause(7) == 14


def test_needs_human_review_raises_with_payload() -> None:
    with pytest.raises(tentacle.NeedsHumanReview) as exc:
        raise tentacle.NeedsHumanReview("pick one", payload={"options": ["a", "b"]})

    assert exc.value.prompt == "pick one"
    assert exc.value.payload == {"options": ["a", "b"]}
