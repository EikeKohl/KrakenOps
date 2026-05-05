"""Workstreams (ADR 0006) — repo, subscriber, and HTTP routes."""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import text

from app.db import engine
from app.realtime import BUS
from app.workstreams import repo
from app.workstreams.subscriber import workstreams_loop


# --- repo ---------------------------------------------------------------


def test_upsert_external_workstream_inserts_then_refreshes(truncate_db) -> None:
    ws_id_a = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="sess-A", label="A", now_s=1000,
    )
    ws_id_b = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="sess-A", label="A2", now_s=2000,
    )
    # Same identity → same id.
    assert ws_id_a == ws_id_b

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT label, started_at_s, last_seen_at_s FROM workstreams WHERE id = :id"
            ),
            {"id": ws_id_a},
        ).first()
    # Label is *not* clobbered on subsequent observations (auto-discovery is
    # ignorant of late-arriving labels — that's the bind/MCP path's job).
    assert row[0] == "A"
    assert row[1] == 1000
    assert row[2] == 2000


def test_bind_then_unbind(truncate_db) -> None:
    # Need a ticket row for the FK to resolve.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES ('PVT_a', 'A', 'me', :ts)"
            ),
            {"ts": int(time.time())},
        )
        conn.execute(
            text(
                "INSERT INTO tickets (id, title, status, project_id, updated_at_s, last_seen_at_s)"
                " VALUES ('T-1', 't', 'Todo', 'PVT_a', :ts, :ts)"
            ),
            {"ts": int(time.time())},
        )

    ws_id = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="sess-X", label="X",
    )

    assert repo.bind_workstream(
        engine, ws_id, ticket_id="T-1", project_id=None, method="manual",
    )

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT ticket_id, project_id, bind_method FROM workstreams WHERE id = :id"
            ),
            {"id": ws_id},
        ).first()
    # project_id was inferred from the ticket because the request omitted it.
    assert row == ("T-1", "PVT_a", "manual")

    assert repo.unbind_workstream(engine, ws_id)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT ticket_id, project_id FROM workstreams WHERE id = :id"),
            {"id": ws_id},
        ).first()
    assert row == (None, None)


def test_bind_unknown_returns_false(truncate_db) -> None:
    assert (
        repo.bind_workstream(
            engine, 999_999, ticket_id="missing", project_id=None, method="manual",
        )
        is False
    )


def test_list_active_window_excludes_old_rows(truncate_db) -> None:
    now_s = int(time.time())
    fresh_id = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="fresh", label="fresh", now_s=now_s,
    )
    repo.upsert_external_workstream(
        engine, source="claude_code", external_id="old", label="old",
        now_s=now_s - (repo.ACTIVE_WINDOW_S + 60),
    )
    rows = repo.list_active_workstreams(engine, now_s=now_s)
    assert {r["id"] for r in rows} == {fresh_id}


# --- subscriber ---------------------------------------------------------


async def _drain_one(queue: asyncio.Queue[dict]) -> None:
    """Run the subscriber long enough to handle a single frame."""
    task = asyncio.create_task(workstreams_loop(engine, queue))
    # Give the loop a tick to consume the queue.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if queue.empty():
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_subscriber_creates_workstream_from_claude_event(truncate_db) -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    await queue.put(
        {
            "topic": "events",
            "ts": time.time_ns(),
            "data": {
                "kind": "event",
                "service_name": "claude-code",
                "event_name": "user_prompt",
                "session_id": "sess-from-event",
                "prompt_id": "pp-1",
                "attributes": {"session.id": "sess-from-event"},
                "observed_at_ns": time.time_ns(),
            },
        }
    )
    await _drain_one(queue)

    rows = repo.list_active_workstreams(engine)
    assert len(rows) == 1
    assert rows[0]["source"] == "claude_code"
    assert rows[0]["external_id"] == "sess-from-event"
    assert rows[0]["label"].startswith("Claude Code · sess sess-fro")


@pytest.mark.asyncio
async def test_subscriber_ignores_non_claude_events(truncate_db) -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    await queue.put(
        {
            "topic": "events",
            "ts": time.time_ns(),
            "data": {
                "kind": "event",
                "service_name": "some-other-tool",
                "event_name": "thing",
                "session_id": "sess-other",
                "attributes": {"session.id": "sess-other"},
                "observed_at_ns": time.time_ns(),
            },
        }
    )
    await _drain_one(queue)
    assert repo.list_active_workstreams(engine) == []


# --- HTTP routes ---------------------------------------------------------


def test_get_workstreams_empty(client) -> None:
    resp = client.get("/v1/workstreams")
    assert resp.status_code == 200
    assert resp.json() == {"workstreams": []}


def test_bind_endpoint_404_unknown(client) -> None:
    resp = client.post("/v1/workstreams/999/bind", json={"ticket_id": "missing"})
    assert resp.status_code == 404


def test_bind_endpoint_succeeds_and_publishes(client) -> None:
    # Seed a project, ticket, and workstream.
    now_s = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES ('PVT_a', 'A', 'me', :ts)"
            ),
            {"ts": now_s},
        )
        conn.execute(
            text(
                "INSERT INTO tickets (id, title, status, project_id, updated_at_s, last_seen_at_s)"
                " VALUES ('T-1', 't', 'Todo', 'PVT_a', :ts, :ts)"
            ),
            {"ts": now_s},
        )
    ws_id = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="abc", label="abc",
    )

    # Subscribe to verify the published frame.
    queue = BUS.subscribe(["workstreams"])

    resp = client.post(
        f"/v1/workstreams/{ws_id}/bind",
        json={"ticket_id": "T-1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"bound": True, "bind_method": "manual"}

    # Confirm a frame landed on the workstreams topic.
    msg = queue.get_nowait()
    assert msg["topic"] == "workstreams"
    [row] = msg["data"]["workstreams"]
    assert row["ticket_id"] == "T-1"
    assert row["project_id"] == "PVT_a"
    assert row["bind_method"] == "manual"


def test_unbind_endpoint(client) -> None:
    ws_id = repo.upsert_external_workstream(
        engine, source="claude_code", external_id="u", label="u",
    )
    # No-op bind to NULL is fine — exercises the SQL path either way.
    resp = client.post(f"/v1/workstreams/{ws_id}/unbind")
    assert resp.status_code == 200
    assert resp.json() == {"bound": False}


def test_list_projects_route(client) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES ('PVT_a', 'Backend', 'acme', :ts)"
            ),
            {"ts": int(time.time())},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES ('PVT_b', 'Frontend', 'acme', :ts)"
            ),
            {"ts": int(time.time())},
        )
    resp = client.get("/v1/projects")
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()["projects"]]
    assert titles == ["Backend", "Frontend"]
