"""Tests for tentacle.init() configuration behavior."""

from __future__ import annotations

import pytest

import tentacle
from tentacle import _core


@pytest.fixture(autouse=True)
def reset_init_state() -> None:
    """Reset module-level init flag before/after each test in this file."""
    _core._reset_for_tests()
    yield
    _core._reset_for_tests()


def test_init_with_explicit_endpoint() -> None:
    tentacle.init(endpoint="http://localhost:1/__nowhere__")
    assert _core._is_initialized() is True


def test_init_idempotency() -> None:
    tentacle.init(endpoint="http://localhost:1/__nowhere__")
    # Second call must be a silent no-op — no exception, no double-config.
    tentacle.init(endpoint="http://localhost:1/__different__")
    assert _core._is_initialized() is True


def test_init_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENTACLE_ENDPOINT", "http://localhost:1/__envvar__")
    tentacle.init()
    assert _core._is_initialized() is True


def test_init_disabled_instrumentation_does_not_raise() -> None:
    # Even when extras aren't installed, init() must not raise.
    tentacle.init(
        endpoint="http://localhost:1/__nowhere__",
        enable_openai=True,
        enable_anthropic=True,
    )
    assert _core._is_initialized() is True
