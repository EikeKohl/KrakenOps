"""Claude Code hook ingestion + ticket status mutation (ADR 0007)."""

from __future__ import annotations

import time

from sqlalchemy import text

from app.db import engine
from app.workstreams import repo


# --- /v1/hooks/claude/post-tool-use ---------------------------------------


def test_post_tool_use_creates_workstream_and_stores_todos(client) -> None:
    body = {
        "session_id": "sess-1",
        "hook_event_name": "PostToolUse",
        "tool_name": "TodoWrite",
        "tool_input": {
            "todos": [
                {"content": "Plan the work", "activeForm": "Planning", "status": "completed"},
                {"content": "Build the thing", "activeForm": "Building", "status": "in_progress"},
                {"content": "Ship it", "activeForm": "Shipping", "status": "pending"},
            ],
        },
    }
    resp = client.post("/v1/hooks/claude/post-tool-use", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["todos_count"] == 3

    rows = repo.list_active_workstreams(engine)
    assert len(rows) == 1
    assert rows[0]["external_id"] == "sess-1"
    assert [t["status"] for t in rows[0]["todos"]] == [
        "completed",
        "in_progress",
        "pending",
    ]


def test_post_tool_use_ignores_non_todowrite(client) -> None:
    body = {
        "session_id": "sess-2",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    resp = client.post("/v1/hooks/claude/post-tool-use", json=body)
    assert resp.status_code == 200
    assert resp.json()["todos_count"] is None

    # Workstream upserts even though no todos persisted.
    rows = repo.list_active_workstreams(engine)
    assert len(rows) == 1
    assert rows[0]["todos"] == []


def test_post_tool_use_filters_malformed_items(client) -> None:
    body = {
        "session_id": "sess-3",
        "tool_name": "TodoWrite",
        "tool_input": {
            "todos": [
                {"content": "valid", "status": "pending"},
                {"status": "pending"},  # missing content
                "not-a-dict",
                {"content": "weird-status", "status": "exploded"},  # status normalized
            ],
        },
    }
    resp = client.post("/v1/hooks/claude/post-tool-use", json=body)
    assert resp.status_code == 200
    rows = repo.list_active_workstreams(engine)
    assert len(rows[0]["todos"]) == 2  # valid + weird-status
    assert rows[0]["todos"][1]["status"] == "pending"  # normalized


def test_post_tool_use_400_without_session_id(client) -> None:
    resp = client.post("/v1/hooks/claude/post-tool-use", json={"tool_name": "TodoWrite"})
    assert resp.status_code == 400


def test_post_tool_use_400_on_garbage_body(client) -> None:
    resp = client.post(
        "/v1/hooks/claude/post-tool-use",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_post_tool_use_publishes_ws_frame(client) -> None:
    """Dashboard sees TODOs within one round-trip."""
    from app.realtime import BUS

    queue = BUS.subscribe(["workstreams"])
    body = {
        "session_id": "sess-broadcast",
        "tool_name": "TodoWrite",
        "tool_input": {"todos": [{"content": "a", "status": "pending"}]},
    }
    resp = client.post("/v1/hooks/claude/post-tool-use", json=body)
    assert resp.status_code == 200
    msg = queue.get_nowait()
    assert msg["topic"] == "workstreams"
    assert any(
        w["external_id"] == "sess-broadcast" and len(w["todos"]) == 1
        for w in msg["data"]["workstreams"]
    )


# --- /v1/hooks/claude/session-start, session-end --------------------------


def test_session_start_creates_workstream(client) -> None:
    resp = client.post(
        "/v1/hooks/claude/session-start", json={"session_id": "sess-start"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-start"
    assert body["workstream_id"] > 0


def test_session_end_marks_ended(client) -> None:
    client.post("/v1/hooks/claude/session-start", json={"session_id": "sess-end"})
    resp = client.post(
        "/v1/hooks/claude/session-end", json={"session_id": "sess-end"}
    )
    assert resp.status_code == 200
    assert resp.json()["ended"] is True

    # The ended workstream falls out of the active list.
    assert repo.list_active_workstreams(engine) == []
    # …but is still queryable in full history.
    rows = repo.list_workstreams(engine)
    assert len(rows) == 1
    assert rows[0]["ended_at_s"] is not None


# --- /v1/tickets/{id}/status ----------------------------------------------


def _seed_ticket(ticket_id: str = "T-A", project_id: str = "PVT_a") -> None:
    now_s = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES (:id, 'A', 'me', :ts)"
            ),
            {"id": project_id, "ts": now_s},
        )
        conn.execute(
            text(
                "INSERT INTO tickets"
                " (id, title, status, project_id, updated_at_s, last_seen_at_s)"
                " VALUES (:id, 't', 'In Progress', :pid, :ts, :ts)"
            ),
            {"id": ticket_id, "pid": project_id, "ts": now_s},
        )


class _RecordingClient:
    """Stand-in for GitHubGraphQLClient — captures calls without I/O."""

    project_id = "PVT_a"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def set_status(self, ticket_id: str, status: str) -> None:
        self.calls.append((ticket_id, status))

    async def aclose(self) -> None:
        return None


def test_set_ticket_status_pushes_via_per_project_client(client) -> None:
    _seed_ticket()
    fake = _RecordingClient()
    client.app.state.github_clients = [fake]

    resp = client.post(
        "/v1/tickets/T-A/status",
        json={"status": "Done", "agent_session_id": "sess-x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ticket_id": "T-A", "status": "Done", "agent_session_id": "sess-x"}
    assert fake.calls == [("T-A", "Done")]

    # Local row reflects the optimistic update.
    with engine.begin() as conn:
        new_status = conn.execute(
            text("SELECT status FROM tickets WHERE id = 'T-A'"),
        ).scalar()
    assert new_status == "Done"


def test_set_ticket_status_404_unknown(client) -> None:
    client.app.state.github_clients = [_RecordingClient()]
    resp = client.post(
        "/v1/tickets/missing/status", json={"status": "Done"},
    )
    assert resp.status_code == 404


def test_set_ticket_status_400_no_status(client) -> None:
    _seed_ticket()
    client.app.state.github_clients = [_RecordingClient()]
    resp = client.post("/v1/tickets/T-A/status", json={})
    assert resp.status_code == 400


def test_set_ticket_status_503_when_no_client(client) -> None:
    _seed_ticket()
    client.app.state.github_clients = []
    client.app.state.github_client = None
    resp = client.post("/v1/tickets/T-A/status", json={"status": "Done"})
    assert resp.status_code == 503
