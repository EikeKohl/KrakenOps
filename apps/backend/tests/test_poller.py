"""Poller tick: ticket mirror, kanban broadcast, agent dispatch.

Tests substitute a recording dispatch function so no real subprocesses are
spawned — that path is exercised by test_orchestrator.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config_file import AgentConfig
from app.db import engine
from app.poller import FakeGitHubClient, TicketItem, tick


def _agent(name: str, script: Path, label: str | None = None) -> AgentConfig:
    return AgentConfig(name=name, script_path=script, match_label=label)


def _ticket(ticket_id: str, status: str, label: str | None = None) -> TicketItem:
    return TicketItem(
        id=ticket_id, title=f"ticket {ticket_id}", status=status,
        url=f"https://github.com/x/y/issues/{ticket_id}",
        labels=[label] if label else [],
    )


@pytest.fixture(autouse=True)
def _clean_orchestration_tables(truncate_db) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM tickets"))


def _recorder():
    """Return (calls, dispatch) — calls is a list of dispatch kwargs captured."""
    calls: list[dict] = []

    def dispatch(**kwargs) -> asyncio.Task:
        calls.append(kwargs)

        async def _noop():
            return None

        return asyncio.create_task(_noop())

    return calls, dispatch


async def test_first_tick_mirrors_tickets_and_broadcasts() -> None:
    gh = FakeGitHubClient(items=[_ticket("A", "Todo")])
    received: list[tuple[str, dict]] = []
    _, dispatch = _recorder()

    summary = await tick(
        engine, gh, agents=[], backend_endpoint="http://x/v1/traces",
        publish=lambda topic, data: (received.append((topic, data)), 1)[1],
        dispatch=dispatch,
    )

    assert summary["ok"] is True
    assert summary["items"] == 1
    assert summary["spawned"] == []  # no agents configured

    [(topic, data)] = received
    assert topic == "kanban"
    assert len(data["tickets"]) == 1
    assert data["tickets"][0]["id"] == "A"

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, status FROM tickets")).all()
    assert dict(rows) == {"A": "Todo"}


async def test_label_match_assigns_agent_and_dispatches(tmp_path: Path) -> None:
    gh = FakeGitHubClient(items=[
        _ticket("A", "Todo", label="research"),
        _ticket("B", "Todo", label="other"),
    ])
    agents = [_agent("research", tmp_path / "noop.py", label="research")]
    calls, dispatch = _recorder()

    summary = await tick(
        engine, gh, agents=agents, backend_endpoint="http://x/v1/traces",
        publish=lambda *a: 0, dispatch=dispatch,
    )

    assert summary["spawned"] == ["A"]
    assert len(calls) == 1
    assert calls[0]["ticket_id"] == "A"
    assert calls[0]["agent"].name == "research"

    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, agent FROM tickets")).all())
    assert rows == {"A": "research", "B": None}


async def test_no_dispatch_when_status_unchanged(tmp_path: Path) -> None:
    gh = FakeGitHubClient(items=[_ticket("A", "Todo", label="research")])
    agents = [_agent("research", tmp_path / "noop.py", label="research")]
    calls, dispatch = _recorder()

    first = await tick(
        engine, gh, agents=agents, backend_endpoint="x", publish=lambda *a: 0, dispatch=dispatch,
    )
    second = await tick(
        engine, gh, agents=agents, backend_endpoint="x", publish=lambda *a: 0, dispatch=dispatch,
    )

    assert first["spawned"] == ["A"]
    assert second["spawned"] == []  # already-Todo doesn't re-spawn
    assert len(calls) == 1


async def test_transition_into_todo_triggers_dispatch(tmp_path: Path) -> None:
    item = _ticket("A", "In Progress", label="research")
    gh = FakeGitHubClient(items=[item])
    agents = [_agent("research", tmp_path / "noop.py", label="research")]
    calls, dispatch = _recorder()

    first = await tick(
        engine, gh, agents=agents, backend_endpoint="x", publish=lambda *a: 0, dispatch=dispatch,
    )
    assert first["spawned"] == []  # not Todo
    assert calls == []

    # Move into Todo.
    gh._items["A"] = TicketItem(id="A", title="t", status="Todo", url=None, labels=["research"])
    second = await tick(
        engine, gh, agents=agents, backend_endpoint="x", publish=lambda *a: 0, dispatch=dispatch,
    )
    assert second["spawned"] == ["A"]
    assert len(calls) == 1


async def test_github_failure_does_not_crash() -> None:
    class Boom(FakeGitHubClient):
        async def list_items(self):
            raise RuntimeError("network down")

    summary = await tick(
        engine, Boom(), agents=[], backend_endpoint="x",
        publish=lambda *a: 0, dispatch=lambda **kw: None,
    )
    assert summary == {"ok": False, "items": 0, "spawned": []}
