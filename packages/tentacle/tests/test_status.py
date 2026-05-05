"""tentacle.register_workstream / claim_ticket / set_status / set_todos.

The transport is plain ``urllib.request.urlopen`` — we patch that so
tests don't hit a real backend.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from typing import Any

import pytest

from tentacle import _status


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        self._buf.close()

    def read(self) -> bytes:
        return self._buf.read()


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Capture every urlopen call as ``{url, body}`` and reply with a stub."""
    captured_calls: list[dict[str, Any]] = []

    def _fake_urlopen(req: Any, timeout: float | None = None) -> _FakeResponse:
        body = req.data.decode() if req.data else ""
        captured_calls.append(
            {
                "url": req.full_url,
                "body": json.loads(body) if body else None,
                "method": req.get_method(),
            }
        )
        # Echo a permissive payload — most tests just assert what was sent.
        return _FakeResponse({"ok": True})

    monkeypatch.setattr(
        "tentacle._status.urllib.request.urlopen", _fake_urlopen
    )
    monkeypatch.setattr("tentacle._status._session_id", None, raising=False)
    monkeypatch.setattr("tentacle._status._api_base", None, raising=False)

    yield captured_calls
    _status._reset_for_tests()


def test_register_workstream_uses_default_endpoint(
    captured: list[dict[str, Any]],
) -> None:
    sid = _status.register_workstream(label="my agent")
    assert isinstance(sid, str) and len(sid) > 0
    [call] = captured
    assert call["url"] == "http://localhost:8787/v1/workstreams/register"
    assert call["body"] == {
        "source": "tentacle",
        "external_id": sid,
        "label": "my agent",
    }


def test_register_workstream_honors_explicit_session_id(
    captured: list[dict[str, Any]],
) -> None:
    sid = _status.register_workstream(session_id="explicit-id")
    assert sid == "explicit-id"
    assert captured[0]["body"]["external_id"] == "explicit-id"


def test_init_sets_api_base_for_status_calls(
    monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]],
) -> None:
    _status._set_api_base("http://10.0.0.5:8888/v1/traces")
    _status.register_workstream(label="x")
    assert captured[0]["url"] == "http://10.0.0.5:8888/v1/workstreams/register"


def test_env_var_overrides_init_endpoint(
    monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]],
) -> None:
    _status._set_api_base("http://10.0.0.5:8888/v1/traces")
    monkeypatch.setenv("KRAKENOPS_API", "http://override:9000")
    _status.register_workstream(label="x")
    assert captured[0]["url"] == "http://override:9000/v1/workstreams/register"


def test_claim_ticket_uses_module_session(
    captured: list[dict[str, Any]],
) -> None:
    _status.register_workstream(session_id="sess-claim")
    _status.claim_ticket("PVTI_xyz")
    # First call is register, second is claim.
    claim_call = captured[1]
    assert claim_call["url"].endswith("/v1/workstreams/claim")
    assert claim_call["body"] == {
        "ticket_id": "PVTI_xyz",
        "session_id": "sess-claim",
        "project_id": None,
        "source": "tentacle",
    }


def test_set_status_posts_to_per_ticket_endpoint(
    captured: list[dict[str, Any]],
) -> None:
    _status.set_status("PVTI_xyz", "Done", session_id="explicit")
    [call] = captured
    assert call["url"].endswith("/v1/tickets/PVTI_xyz/status")
    assert call["body"] == {"status": "Done", "agent_session_id": "explicit"}


def test_set_todos_posts_full_list(captured: list[dict[str, Any]]) -> None:
    _status.register_workstream(session_id="sess-todos")
    _status.set_todos(
        [
            {"content": "do x", "status": "completed"},
            {"content": "do y", "status": "in_progress"},
        ],
    )
    todos_call = captured[1]
    assert todos_call["url"].endswith("/v1/workstreams/todos")
    assert todos_call["body"]["session_id"] == "sess-todos"
    assert todos_call["body"]["source"] == "tentacle"
    assert len(todos_call["body"]["todos"]) == 2


def test_status_calls_swallow_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent code keeps running even when the backend is unreachable
    (ADR 0008 §"Negative / accepted risks")."""
    import urllib.error

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.URLError("backend down")

    monkeypatch.setattr("tentacle._status.urllib.request.urlopen", _boom)

    # All three should return an empty dict, not raise.
    assert _status.claim_ticket("PVTI_xyz") == {}
    assert _status.set_status("PVTI_xyz", "Done") == {}
    assert _status.set_todos([]) == {}


def test_register_workstream_returns_id_even_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error

    monkeypatch.setattr(
        "tentacle._status.urllib.request.urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("nope")),
    )
    sid = _status.register_workstream(label="offline")
    assert isinstance(sid, str) and len(sid) > 0
    # Subsequent calls still attribute to this session id.
    assert _status._effective_session_id(None) == sid
