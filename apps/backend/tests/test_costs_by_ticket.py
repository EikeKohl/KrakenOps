"""/v1/costs?group_by=ticket — Claude Code cost rollup per bound ticket
(ADR 0008)."""

from __future__ import annotations

import json
import time

from sqlalchemy import text

from app.db import engine


def _seed_project_and_ticket(
    project_id: str = "PVT_a",
    ticket_id: str = "T-1",
    project_title: str = "Backend",
    ticket_title: str = "Add billing webhook",
) -> None:
    now_s = int(time.time())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO projects (id, title, owner_login, last_seen_at_s)"
                " VALUES (:pid, :ptitle, 'me', :ts)"
            ),
            {"pid": project_id, "ptitle": project_title, "ts": now_s},
        )
        conn.execute(
            text(
                "INSERT INTO tickets"
                " (id, title, status, project_id, updated_at_s, last_seen_at_s)"
                " VALUES (:tid, :title, 'In Progress', :pid, :ts, :ts)"
            ),
            {"tid": ticket_id, "title": ticket_title, "pid": project_id, "ts": now_s},
        )


def _seed_workstream(session_id: str, ticket_id: str | None) -> int:
    now_s = int(time.time())
    with engine.begin() as conn:
        cur = conn.execute(
            text(
                "INSERT INTO workstreams"
                " (source, external_id, label, ticket_id, started_at_s, last_seen_at_s)"
                " VALUES ('claude_code', :ext, :label, :tid, :ts, :ts)"
            ),
            {"ext": session_id, "label": session_id[:12], "tid": ticket_id, "ts": now_s},
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def _emit_cost_metric(session_id: str, value: float, ts_ns: int | None = None) -> None:
    ts = ts_ns if ts_ns is not None else time.time_ns()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO external_metrics"
                " (service_name, metric_name, value, unit, attributes_json, ts_ns)"
                " VALUES ('claude-code', 'claude_code.cost.usage', :v, 'USD', :attrs, :ts)"
            ),
            {
                "v": value,
                "attrs": json.dumps({"session.id": session_id}),
                "ts": ts,
            },
        )


def test_default_group_by_model_unchanged(client) -> None:
    """Existing /v1/costs callers (the dashboard's CostsStrip) keep working."""
    resp = client.get("/v1/costs?window=24h")
    assert resp.status_code == 200
    body = resp.json()
    assert "by_model" in body
    assert "by_ticket" not in body


def test_group_by_ticket_sums_costs_through_workstream(client) -> None:
    _seed_project_and_ticket()
    _seed_workstream("sess-A", ticket_id="T-1")
    _emit_cost_metric("sess-A", 0.10)
    _emit_cost_metric("sess-A", 0.30)

    resp = client.get("/v1/costs?window=24h&group_by=ticket")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_cost_usd"] == 0.40
    [row] = body["by_ticket"]
    assert row["ticket_id"] == "T-1"
    assert row["ticket_title"] == "Add billing webhook"
    assert row["project_id"] == "PVT_a"
    assert row["project_title"] == "Backend"
    assert row["cost_usd"] == 0.40
    assert row["calls"] == 2


def test_group_by_ticket_drops_unbound_workstreams(client) -> None:
    _seed_project_and_ticket()
    _seed_workstream("sess-bound", ticket_id="T-1")
    _seed_workstream("sess-unbound", ticket_id=None)
    _emit_cost_metric("sess-bound", 0.15)
    _emit_cost_metric("sess-unbound", 999.00)

    body = client.get("/v1/costs?window=24h&group_by=ticket").json()
    [row] = body["by_ticket"]
    assert row["ticket_id"] == "T-1"
    assert row["cost_usd"] == 0.15  # unbound session's cost not attributed


def test_group_by_ticket_respects_window(client) -> None:
    _seed_project_and_ticket()
    _seed_workstream("sess-old", ticket_id="T-1")
    _seed_workstream("sess-new", ticket_id="T-1")
    twenty_five_h_ago = time.time_ns() - 25 * 60 * 60 * 1_000_000_000
    _emit_cost_metric("sess-old", 100.00, ts_ns=twenty_five_h_ago)
    _emit_cost_metric("sess-new", 0.50)

    body = client.get("/v1/costs?window=24h&group_by=ticket").json()
    [row] = body["by_ticket"]
    assert row["cost_usd"] == 0.50


def test_group_by_ticket_invalid_value_400(client) -> None:
    resp = client.get("/v1/costs?window=24h&group_by=garbage")
    # FastAPI's pattern validation surfaces as 422.
    assert resp.status_code in {400, 422}
