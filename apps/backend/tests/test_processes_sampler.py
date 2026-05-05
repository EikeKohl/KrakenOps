"""Per-process sampler (ADR 0005).

We unit-test the pure helpers — allowlist matching, upsert, sweep — against
a fake snapshot. We do NOT spin up `psutil.process_iter` here; that's a
moving target across hosts.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db import engine
from app.sampler.processes import (
    _purge_denylisted,
    matches_allowlist,
    matches_denylist,
    sweep_stale,
    upsert_processes,
)


def test_matches_allowlist_case_insensitive_substring() -> None:
    cmd = "/usr/local/bin/node /Applications/Claude.app/Contents/Resources/cli.js"
    assert matches_allowlist(cmd, ["claude"]) is True
    assert matches_allowlist(cmd, ["CLAUDE"]) is True
    assert matches_allowlist(cmd, ["cursor", "claude"]) is True
    assert matches_allowlist(cmd, ["cursor"]) is False
    # Empty allowlist or empty command → no match.
    assert matches_allowlist(cmd, []) is False
    assert matches_allowlist("", ["claude"]) is False
    # Empty entries are skipped (they would match everything).
    assert matches_allowlist(cmd, ["", "claude"]) is True
    assert matches_allowlist(cmd, [""]) is False


def test_upsert_inserts_then_updates(truncate_db) -> None:
    snapshot_first = [
        {
            "pid": 12345,
            "name": "node",
            "cmdline": "node /Applications/Claude.app/cli.js",
            "cpu_pct": 1.5,
            "rss_mb": 220.0,
            "started_at_s": 1_700_000_000.0,
            "observed_ns": 1_000_000_000_000,
        }
    ]
    upsert_processes(engine, snapshot_first)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT pid, name, cmdline, last_cpu_pct, last_rss_mb,"
                " first_seen_ns, last_seen_ns FROM discovered_processes"
            )
        ).all()
    assert len(rows) == 1
    assert int(rows[0][0]) == 12345
    assert rows[0][3] == 1.5
    assert int(rows[0][5]) == 1_000_000_000_000  # first_seen
    assert int(rows[0][6]) == 1_000_000_000_000  # last_seen

    # Second tick: same PID, fresh values. first_seen must NOT change; last_seen does.
    snapshot_second = [
        {
            **snapshot_first[0],
            "cpu_pct": 7.2,
            "rss_mb": 240.0,
            "observed_ns": 2_000_000_000_000,
        }
    ]
    upsert_processes(engine, snapshot_second)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT last_cpu_pct, last_rss_mb, first_seen_ns, last_seen_ns"
                " FROM discovered_processes WHERE pid = 12345"
            )
        ).all()
    assert rows[0][0] == 7.2
    assert rows[0][1] == 240.0
    assert int(rows[0][2]) == 1_000_000_000_000  # unchanged
    assert int(rows[0][3]) == 2_000_000_000_000


def test_sweep_drops_rows_older_than_threshold(truncate_db) -> None:
    now_ns = 10_000_000_000_000
    one_hour_ns = 60 * 60 * 1_000_000_000

    snapshot = [
        {
            "pid": 1,
            "name": "fresh",
            "cmdline": "claude --fresh",
            "cpu_pct": 0.0,
            "rss_mb": 0.0,
            "started_at_s": 0.0,
            "observed_ns": now_ns - 5 * 1_000_000_000,  # 5s ago
        },
        {
            "pid": 2,
            "name": "stale",
            "cmdline": "claude --stale",
            "cpu_pct": 0.0,
            "rss_mb": 0.0,
            "started_at_s": 0.0,
            "observed_ns": now_ns - (one_hour_ns + 60 * 1_000_000_000),  # 1h+1min ago
        },
    ]
    upsert_processes(engine, snapshot)

    deleted = sweep_stale(engine, now_ns)
    assert deleted == 1

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT pid FROM discovered_processes")).all()
    assert {int(r[0]) for r in rows} == {1}


def test_sweep_no_rows_is_safe(truncate_db) -> None:
    # Empty table → nothing to sweep, no error.
    deleted = sweep_stale(engine, 1_000_000_000_000)
    assert deleted == 0


def test_get_processes_returns_inserted_rows(client) -> None:
    """/v1/processes returns the latest snapshot, sorted by last_seen DESC."""
    upsert_processes(
        engine,
        [
            {
                "pid": 11,
                "name": "node",
                "cmdline": "claude foo",
                "cpu_pct": 1.0,
                "rss_mb": 50.0,
                "started_at_s": 0.0,
                "observed_ns": 1_000,
            },
            {
                "pid": 22,
                "name": "node",
                "cmdline": "claude bar",
                "cpu_pct": 2.0,
                "rss_mb": 75.0,
                "started_at_s": 0.0,
                "observed_ns": 2_000,
            },
        ],
    )

    listing = client.get("/v1/processes").json()
    assert len(listing["processes"]) == 2
    # PID 22 was observed later → comes first.
    assert listing["processes"][0]["pid"] == 22
    assert listing["processes"][1]["pid"] == 11
    assert listing["processes"][0]["cpu_pct"] == 2.0
    assert listing["processes"][0]["rss_mb"] == 75.0


def test_matches_denylist_filters_shell_noise() -> None:
    cmd = "/bin/zsh -i"
    assert matches_denylist(cmd, ["/bin/zsh", "/bin/bash"]) is True
    assert matches_denylist("python script.py", ["/bin/zsh"]) is False
    # Empty denylist short-circuits to False.
    assert matches_denylist(cmd, []) is False
    assert matches_denylist("", ["/bin/zsh"]) is False


def test_purge_denylisted_removes_matching_rows(truncate_db) -> None:
    upsert_processes(
        engine,
        [
            {
                "pid": 1,
                "name": "claude",
                "cmdline": "claude --resume xyz",
                "cpu_pct": 0.0,
                "rss_mb": 0.0,
                "started_at_s": 0.0,
                "observed_ns": 1_000,
            },
            {
                "pid": 2,
                "name": "zsh",
                "cmdline": "/bin/zsh -i",
                "cpu_pct": 0.0,
                "rss_mb": 0.0,
                "started_at_s": 0.0,
                "observed_ns": 2_000,
            },
        ],
    )
    deleted = _purge_denylisted(engine, ("/bin/zsh",))
    assert deleted == 1
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT pid FROM discovered_processes")).all()
    assert {int(r[0]) for r in rows} == {1}


def test_kill_endpoint_refuses_unknown_pid(client) -> None:
    """Without the row in discovered_processes, the endpoint must 404."""
    resp = client.post("/v1/processes/999999/kill")
    assert resp.status_code == 404
    assert "discovered" in resp.json()["detail"].lower()


def test_kill_endpoint_refuses_invalid_pid(client) -> None:
    resp = client.post("/v1/processes/0/kill")
    assert resp.status_code == 400


def test_kill_endpoint_refuses_self(client) -> None:
    """Backend's own pid must never be killable through this surface."""
    import os

    upsert_processes(
        engine,
        [
            {
                "pid": os.getpid(),
                "name": "uvicorn",
                "cmdline": "uvicorn app.main:app",
                "cpu_pct": 0.0,
                "rss_mb": 0.0,
                "started_at_s": 0.0,
                "observed_ns": 1_000,
            }
        ],
    )
    resp = client.post(f"/v1/processes/{os.getpid()}/kill")
    assert resp.status_code == 400
    assert "backend" in resp.json()["detail"].lower()


def test_get_processes_respects_limit(client) -> None:
    rows = [
        {
            "pid": 1000 + i,
            "name": f"proc{i}",
            "cmdline": f"claude {i}",
            "cpu_pct": 0.0,
            "rss_mb": 0.0,
            "started_at_s": 0.0,
            "observed_ns": 1_000_000_000 + i,
        }
        for i in range(5)
    ]
    upsert_processes(engine, rows)
    listing = client.get("/v1/processes", params={"limit": 2}).json()
    assert len(listing["processes"]) == 2
