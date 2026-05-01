"""GET /v1/tickets and GET /v1/agents."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine


@pytest.fixture(autouse=True)
def _seed_orchestration(truncate_db) -> None:
    now = int(time.time())
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM tickets"))
        conn.execute(
            text(
                "INSERT INTO tickets (id, title, status, url, agent, updated_at_s, last_seen_at_s)"
                " VALUES ('A', 'first',  'Todo',                'https://x/1', 'r', :n,    :n)"
            ),
            {"n": now},
        )
        conn.execute(
            text(
                "INSERT INTO tickets (id, title, status, url, agent, updated_at_s, last_seen_at_s)"
                " VALUES ('B', 'second', 'Needs Human Review',  'https://x/2', 'r', :n2,   :n2)"
            ),
            {"n2": now - 60},
        )
        conn.execute(
            text(
                "INSERT INTO agent_runs (ticket_id, agent_name, started_at_s, status, exit_code)"
                " VALUES ('A', 'r', :n, 'running', NULL)"
            ),
            {"n": now},
        )
        conn.execute(
            text(
                "INSERT INTO agent_runs (ticket_id, agent_name, started_at_s, ended_at_s,"
                " status, exit_code) VALUES ('B', 'r', :s, :e, 'needs_human_review', 42)"
            ),
            {"s": now - 120, "e": now - 60},
        )


def test_list_tickets(client: TestClient) -> None:
    r = client.get("/v1/tickets")
    assert r.status_code == 200
    body = r.json()
    ids = [t["id"] for t in body["tickets"]]
    # Newest-first ordering by updated_at_s.
    assert ids == ["A", "B"]
    assert body["tickets"][0]["status"] == "Todo"
    assert body["tickets"][0]["url"] == "https://x/1"


def test_list_agents_unfiltered(client: TestClient) -> None:
    r = client.get("/v1/agents")
    assert r.status_code == 200
    runs = r.json()["runs"]
    statuses = {run["status"] for run in runs}
    assert statuses == {"running", "needs_human_review"}


def test_list_agents_filtered(client: TestClient) -> None:
    r = client.get("/v1/agents", params={"status": "running"})
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["ticket_id"] == "A"
