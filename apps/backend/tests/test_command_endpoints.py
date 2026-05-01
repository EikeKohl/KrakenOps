"""Tests for POST /v1/tickets/{id}/spawn, /resume and POST /v1/agents/{id}/stop.

Tests that touch real subprocesses use httpx.AsyncClient + ASGITransport so the
spawned process and the route that terminates it share one event loop. The
synchronous TestClient spins up a fresh loop per request, which makes the
subprocess unreachable from /stop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy import text

from app.config_file import AgentConfig
from app.db import engine
from app.main import app
from app.poller import FakeGitHubClient, TicketItem
from app.poller import orchestrator as orch_mod

# --- helpers --------------------------------------------------------------


def _seed_ticket(
    ticket_id: str, status: str = "Todo", agent_name: str | None = "default"
) -> None:
    now = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tickets (id, title, status, url, agent, updated_at_s, last_seen_at_s)"
                " VALUES (:id, :title, :st, :url, :agent, :ts, :ts)"
            ),
            {
                "id": ticket_id, "title": f"ticket {ticket_id}", "st": status,
                "url": "https://x", "agent": agent_name, "ts": now,
            },
        )


def _set_state(client_or_app: Any, *, github_client=None, agents=None) -> None:
    """Override app.state. Accepts either a TestClient or the app directly."""
    target = client_or_app.app if hasattr(client_or_app, "app") else client_or_app
    target.state.github_client = github_client
    target.state.agents = agents or []
    target.state.backend_endpoint = "http://127.0.0.1:8787/v1/traces"


def _instant_script(tmp_path: Path) -> Path:
    p = tmp_path / "instant.py"
    p.write_text("import sys; sys.exit(0)\n")
    return p


@pytest.fixture(autouse=True)
def _clean_orchestration_tables(truncate_db) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM tickets"))
    orch_mod.RUNNING.clear()


@pytest.fixture
async def asgi_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# --- /v1/tickets/{id}/spawn ----------------------------------------------


def test_spawn_503_when_poller_dormant(client: TestClient) -> None:
    _set_state(client, github_client=None)
    _seed_ticket("A")
    r = client.post("/v1/tickets/A/spawn")
    assert r.status_code == 503


def test_spawn_404_for_unknown_ticket(client: TestClient) -> None:
    _set_state(client, github_client=FakeGitHubClient(), agents=[])
    r = client.post("/v1/tickets/NOPE/spawn")
    assert r.status_code == 404


def test_spawn_400_when_no_agent_mapping(client: TestClient) -> None:
    _set_state(client, github_client=FakeGitHubClient(), agents=[])
    _seed_ticket("A")
    r = client.post("/v1/tickets/A/spawn")
    assert r.status_code == 400


def test_spawn_409_when_agent_already_running(client: TestClient, tmp_path: Path) -> None:
    _set_state(
        client,
        github_client=FakeGitHubClient(),
        agents=[AgentConfig(name="default", script_path=_instant_script(tmp_path))],
    )
    _seed_ticket("A")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (ticket_id, agent_name, started_at_s, status)"
                " VALUES ('A', 'default', :ts, 'running')"
            ),
            {"ts": int(time.time())},
        )
    r = client.post("/v1/tickets/A/spawn")
    assert r.status_code == 409


async def test_spawn_dispatches_and_completes(
    asgi_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    gh = FakeGitHubClient(
        items=[TicketItem(id="A", title="t", status="Todo", url=None, labels=[])]
    )
    _set_state(
        app,
        github_client=gh,
        agents=[AgentConfig(name="default", script_path=_instant_script(tmp_path))],
    )
    _seed_ticket("A", agent_name="default")

    r = await asgi_client.post("/v1/tickets/A/spawn")
    assert r.status_code == 202
    body = r.json()
    assert body["agent"] == "default"
    assert isinstance(body["run_id"], int)

    # Wait for _finish_run to write the terminal status. RUNNING.pop happens
    # before _finish_run, so polling RUNNING isn't sufficient — we want the
    # DB row's final state.
    deadline = time.time() + 5
    status: str | None = None
    while time.time() < deadline:
        with engine.begin() as conn:
            status = conn.execute(
                text("SELECT status FROM agent_runs WHERE id = :id"),
                {"id": body["run_id"]},
            ).scalar_one()
        if status != "running":
            break
        await asyncio.sleep(0.05)
    assert status == "succeeded"
    assert gh.status_calls == [("A", "Done")]


# --- /v1/tickets/{id}/resume ---------------------------------------------


def test_resume_404_unknown_ticket(client: TestClient) -> None:
    _set_state(client, github_client=FakeGitHubClient())
    r = client.post("/v1/tickets/NOPE/resume")
    assert r.status_code == 404


def test_resume_409_wrong_status(client: TestClient) -> None:
    _set_state(client, github_client=FakeGitHubClient())
    _seed_ticket("A", status="Todo")
    r = client.post("/v1/tickets/A/resume")
    assert r.status_code == 409


def test_resume_503_dormant_poller(client: TestClient) -> None:
    _set_state(client, github_client=None)
    _seed_ticket("A", status="Needs Human Review")
    r = client.post("/v1/tickets/A/resume")
    assert r.status_code == 503


def test_resume_transitions_status(client: TestClient) -> None:
    gh = FakeGitHubClient()
    _set_state(client, github_client=gh)
    _seed_ticket("A", status="Needs Human Review")

    r = client.post("/v1/tickets/A/resume")
    assert r.status_code == 200
    assert r.json() == {"status": "Todo"}
    assert gh.status_calls == [("A", "Todo")]

    with engine.begin() as conn:
        status = conn.execute(text("SELECT status FROM tickets WHERE id = 'A'")).scalar_one()
    assert status == "Todo"


def test_resume_502_on_github_failure(client: TestClient) -> None:
    class Boom(FakeGitHubClient):
        async def set_status(self, item_id, status):
            raise RuntimeError("github 500")

    _set_state(client, github_client=Boom())
    _seed_ticket("A", status="Needs Human Review")
    r = client.post("/v1/tickets/A/resume")
    assert r.status_code == 502


# --- /v1/agents/{id}/stop ------------------------------------------------


def test_stop_404_unknown_run(client: TestClient) -> None:
    r = client.post("/v1/agents/9999/stop")
    assert r.status_code == 404


def test_stop_409_when_not_running(client: TestClient) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (id, ticket_id, agent_name, started_at_s, status)"
                " VALUES (1, 'A', 'a', :ts, 'succeeded')"
            ),
            {"ts": int(time.time())},
        )
    r = client.post("/v1/agents/1/stop")
    assert r.status_code == 409


async def test_stop_terminates_long_running_subprocess(
    asgi_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    script = tmp_path / "sleep.py"
    script.write_text("import time; time.sleep(60)\n")

    gh = FakeGitHubClient()
    agent = AgentConfig(name="long", script_path=script)

    task = asyncio.create_task(
        orch_mod.run_agent(
            engine=engine, github=gh,
            ticket_id="A", ticket_title="A",
            agent=agent, backend_endpoint="x",
        )
    )

    # Wait for the subprocess to enter RUNNING.
    deadline = time.time() + 3
    while time.time() < deadline and not orch_mod.RUNNING:
        await asyncio.sleep(0.05)
    assert orch_mod.RUNNING, "orchestrator never entered RUNNING"
    [run_id] = list(orch_mod.RUNNING.keys())

    r = await asgi_client.post(f"/v1/agents/{run_id}/stop")
    assert r.status_code == 200
    assert r.json() == {"stopped": True}

    await asyncio.wait_for(task, timeout=5)
    with engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM agent_runs WHERE id = :id"), {"id": run_id},
        ).scalar_one()
    assert status == "stopped"
    assert gh.status_calls == []
