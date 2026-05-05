"""Workstream status + TODO publishing for tentacle agents (ADR 0008).

Symmetric with the MCP tools the Claude Code plugin exposes (ADR 0007),
but for non-Claude agents that import this SDK directly. The functions
HTTP-POST to the local KrakenOps backend; failures are logged but never
raised so user agent code keeps running unimpeded.

Public API (re-exported from ``tentacle``):

    tentacle.register_workstream(label=None) -> str
    tentacle.claim_ticket(ticket_id, session_id=None, project_id=None) -> dict
    tentacle.set_status(ticket_id, status, session_id=None) -> dict
    tentacle.set_todos(items, session_id=None) -> dict

The session id registered on the first call is stashed module-locally
and used as the default for all subsequent calls. Set it explicitly if
your process fans out into multiple workstreams.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
import uuid
from typing import Any

_log = logging.getLogger("tentacle.status")
_lock = threading.Lock()

# Module-level state — single workstream per process by default.
_session_id: str | None = None
_api_base: str | None = None

DEFAULT_API_BASE = "http://localhost:8787"
_HTTP_TIMEOUT_S = 5.0


def _api_base_from_traces_endpoint(endpoint: str | None) -> str:
    """Derive the API base from the traces OTel endpoint configured at init.

    ``http://host:port/v1/traces`` → ``http://host:port``.
    """
    if not endpoint:
        return DEFAULT_API_BASE
    base = endpoint.rstrip("/")
    if base.endswith("/v1/traces"):
        base = base[: -len("/v1/traces")]
    return base or DEFAULT_API_BASE


def _set_api_base(endpoint: str | None) -> None:
    """Called by tentacle.init() so the status helpers know where to POST."""
    global _api_base
    with _lock:
        _api_base = _api_base_from_traces_endpoint(endpoint)


def _resolved_api_base() -> str:
    """Honor ``KRAKENOPS_API`` env override, then init's traces endpoint,
    then the local-first default."""
    env_override = os.environ.get("KRAKENOPS_API")
    if env_override:
        return env_override.rstrip("/")
    if _api_base:
        return _api_base
    return DEFAULT_API_BASE


def _post(path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST JSON to the backend. Returns parsed body on success; ``None``
    on any failure (logged, never raised)."""
    url = f"{_resolved_api_base()}{path}"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            data = resp.read().decode()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        _log.warning("krakenops POST %s → HTTP %s: %s", path, e.code, e.reason)
        return None
    except (urllib.error.URLError, TimeoutError) as e:
        _log.warning("krakenops POST %s unreachable: %s", path, e)
        return None
    except Exception as e:  # pragma: no cover - defensive
        _log.warning("krakenops POST %s failed: %s", path, e)
        return None


# --- public API ----------------------------------------------------------


def register_workstream(label: str | None = None, *, session_id: str | None = None) -> str:
    """Register this process as a tentacle workstream (ADR 0008).

    Parameters
    ----------
    label:
        Optional human label rendered on the dashboard's workstream card.
        Defaults to the script's filename + the first 8 chars of the
        session id.
    session_id:
        Optional explicit id. Defaults to a fresh ``uuid4``. Pass
        explicitly when the same logical workstream spans multiple
        processes (e.g. a parent that spawns child workers).

    Returns
    -------
    The registered session id — stash it if you need to thread it
    through subprocess env vars.

    Notes
    -----
    Idempotent server-side on ``(source="tentacle", external_id)``;
    calling twice with the same id refreshes ``last_seen_at_s`` only.
    """
    global _session_id
    sid = session_id or str(uuid.uuid4())
    final_label = label or _default_label(sid)

    _post(
        "/v1/workstreams/register",
        {"source": "tentacle", "external_id": sid, "label": final_label},
    )

    with _lock:
        _session_id = sid
    return sid


def claim_ticket(
    ticket_id: str,
    *,
    session_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Bind this workstream to a GitHub Projects ticket (ADR 0008).

    Mirrors the MCP ``krakenops.claim_ticket`` tool. ``bind_method`` on
    the resulting workstream row is recorded as ``"mcp"`` so the
    dashboard's existing "via MCP" badge styling applies.
    """
    body = {
        "ticket_id": ticket_id,
        "session_id": _effective_session_id(session_id),
        "project_id": project_id,
        "source": "tentacle",
    }
    return _post("/v1/workstreams/claim", body) or {}


def set_status(
    ticket_id: str,
    status: str,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Push a status change for a ticket back to GitHub (ADR 0008).

    ``status`` must match one of the project's "Status" single-select
    options. KrakenOps surfaces a 400 (logged here, returns None) when
    the option doesn't exist on the target project.
    """
    body = {
        "status": status,
        "agent_session_id": _effective_session_id(session_id),
    }
    return _post(f"/v1/tickets/{ticket_id}/status", body) or {}


def set_todos(
    items: list[dict[str, Any]],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Replace this workstream's TODO list (ADR 0008).

    Each item: ``{content, activeForm?, status: pending | in_progress |
    completed}``. Mirrors Claude Code's TodoWrite shape so the
    dashboard's TODO rendering applies uniformly.
    """
    body = {
        "todos": items,
        "session_id": _effective_session_id(session_id),
        "source": "tentacle",
    }
    return _post("/v1/workstreams/todos", body) or {}


# --- internals -----------------------------------------------------------


def _effective_session_id(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    with _lock:
        return _session_id


def _default_label(session_id: str) -> str:
    """Try to surface the script name on the dashboard card. Falls back
    to a generic label if introspection fails (e.g. REPL)."""
    try:
        import sys

        script = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
        if script:
            return f"tentacle · {script}"
    except Exception:
        pass
    return f"tentacle · {session_id[:8]}"


def _reset_for_tests() -> None:
    """Test-only: clear module state."""
    global _session_id, _api_base
    with _lock:
        _session_id = None
        _api_base = None
