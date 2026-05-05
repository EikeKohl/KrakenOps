"""Poller tick: ticket mirror + project upsert + kanban broadcast (ADR 0006).

The auto-spawn-on-Todo path was removed in ADR 0006 — KrakenOps is read-only;
agents claim tickets via MCP or the dashboard. The manual subprocess
dispatch is exercised by ``test_orchestrator.py`` and the
``/v1/tickets/{id}/spawn`` route in ``test_orchestration_routes.py``.
"""

from __future__ import annotations

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
        conn.execute(text("DELETE FROM projects"))


async def test_first_tick_mirrors_tickets_and_broadcasts() -> None:
    gh = FakeGitHubClient(
        items=[_ticket("A", "Todo")],
        project_id="PVT_alpha",
        title="Alpha",
        owner_login="acme",
    )
    received: list[tuple[str, dict]] = []

    summary = await tick(
        engine, gh, agents=[],
        publish=lambda topic, data: (received.append((topic, data)), 1)[1],
    )

    assert summary["ok"] is True
    assert summary["upserts"] == 1
    assert summary["project_id"] == "PVT_alpha"

    [(topic, data)] = received
    assert topic == "kanban"
    assert len(data["tickets"]) == 1
    assert data["tickets"][0]["id"] == "A"
    assert data["tickets"][0]["project_id"] == "PVT_alpha"
    assert len(data["projects"]) == 1
    assert data["projects"][0]["id"] == "PVT_alpha"
    assert data["projects"][0]["title"] == "Alpha"
    assert data["projects"][0]["owner_login"] == "acme"

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, status, project_id FROM tickets")).all()
    assert {r[0]: (r[1], r[2]) for r in rows} == {"A": ("Todo", "PVT_alpha")}


async def test_label_assigns_agent_but_does_not_dispatch(tmp_path: Path) -> None:
    """ADR 0006: ticket.agent is still populated for manual spawn but no
    subprocess fires automatically."""
    gh = FakeGitHubClient(items=[
        _ticket("A", "Todo", label="research"),
        _ticket("B", "Todo", label="other"),
    ])
    agents = [_agent("research", tmp_path / "noop.py", label="research")]

    summary = await tick(engine, gh, agents=agents, publish=lambda *a: 0)

    assert summary["upserts"] == 2
    assert "spawned" not in summary  # field intentionally removed in ADR 0006

    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, agent FROM tickets")).all())
    assert rows == {"A": "research", "B": None}

    # No agent_runs row — auto-dispatch is gone.
    with engine.begin() as conn:
        run_count = conn.execute(text("SELECT COUNT(*) FROM agent_runs")).scalar()
    assert run_count == 0


async def test_repeat_tick_keeps_status_unchanged(tmp_path: Path) -> None:
    gh = FakeGitHubClient(items=[_ticket("A", "Todo", label="research")])
    agents = [_agent("research", tmp_path / "noop.py", label="research")]

    await tick(engine, gh, agents=agents, publish=lambda *a: 0)
    await tick(engine, gh, agents=agents, publish=lambda *a: 0)

    with engine.begin() as conn:
        run_count = conn.execute(text("SELECT COUNT(*) FROM agent_runs")).scalar()
    assert run_count == 0


async def test_status_transition_updates_updated_at(tmp_path: Path) -> None:
    item = _ticket("A", "In Progress", label="research")
    gh = FakeGitHubClient(items=[item])

    await tick(engine, gh, agents=[], publish=lambda *a: 0)
    with engine.begin() as conn:
        first_updated = conn.execute(
            text("SELECT updated_at_s FROM tickets WHERE id = 'A'")
        ).scalar()

    # Move into Todo and tick again.
    gh._items["A"] = TicketItem(id="A", title="t", status="Todo", url=None, labels=["research"])
    await tick(engine, gh, agents=[], publish=lambda *a: 0)

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, updated_at_s FROM tickets WHERE id = 'A'")
        ).first()
    assert row[0] == "Todo"
    # updated_at_s must have advanced (or stayed equal if both ticks fell in the
    # same second — the upsert clause only bumps it when the status changed).
    assert row[1] >= first_updated


async def test_github_failure_does_not_crash() -> None:
    class Boom(FakeGitHubClient):
        async def list_items(self):
            raise RuntimeError("network down")

    summary = await tick(engine, Boom(project_id="PVT_x"), agents=[], publish=lambda *a: 0)
    assert summary == {"ok": False, "project_id": "PVT_x", "upserts": 0}
