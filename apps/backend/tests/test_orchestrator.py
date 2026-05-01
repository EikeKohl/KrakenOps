"""Orchestrator: spawn subprocess, classify exit, update GitHub accordingly."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config_file import AgentConfig
from app.db import engine
from app.poller import FakeGitHubClient, run_agent


def _write_script(tmp: Path, body: str) -> Path:
    p = tmp / "agent.py"
    p.write_text(textwrap.dedent(body))
    return p


def _make_agent(script: Path, name: str = "test-agent") -> AgentConfig:
    return AgentConfig(name=name, script_path=script)


@pytest.fixture(autouse=True)
def _clean_runs(truncate_db) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))


async def test_exit_zero_marks_succeeded_and_updates_github(tmp_path: Path) -> None:
    script = _write_script(tmp_path, """
        import os
        assert os.environ['KRAKENOPS_TICKET_ID'] == 't1'
        assert os.environ['KRAKENOPS_TICKET_TITLE'] == 'hello'
        print('ok')
    """)
    gh = FakeGitHubClient()

    run_id = await run_agent(
        engine=engine, github=gh,
        ticket_id="t1", ticket_title="hello",
        agent=_make_agent(script),
        backend_endpoint="http://x/v1/traces",
    )

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, exit_code, ticket_id FROM agent_runs WHERE id=:id"),
            {"id": run_id},
        ).first()
    assert row[0] == "succeeded"
    assert row[1] == 0
    assert row[2] == "t1"

    assert gh.status_calls == [("t1", "Done")]


async def test_exit_42_marks_human_review(tmp_path: Path) -> None:
    script = _write_script(tmp_path, """
        import sys
        sys.exit(42)
    """)
    gh = FakeGitHubClient()

    run_id = await run_agent(
        engine=engine, github=gh,
        ticket_id="t2", ticket_title="needs review",
        agent=_make_agent(script),
        backend_endpoint="http://x/v1/traces",
    )

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, exit_code FROM agent_runs WHERE id=:id"), {"id": run_id},
        ).first()
    assert row == ("needs_human_review", 42)
    assert gh.status_calls == [("t2", "Needs Human Review")]


async def test_other_nonzero_marks_failed_no_github_update(tmp_path: Path) -> None:
    script = _write_script(tmp_path, """
        raise SystemExit(1)
    """)
    gh = FakeGitHubClient()

    run_id = await run_agent(
        engine=engine, github=gh,
        ticket_id="t3", ticket_title="boom",
        agent=_make_agent(script),
        backend_endpoint="http://x/v1/traces",
    )

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, exit_code FROM agent_runs WHERE id=:id"), {"id": run_id},
        ).first()
    assert row == ("failed", 1)
    assert gh.status_calls == []  # operator follow-up


async def test_stderr_tail_captured(tmp_path: Path) -> None:
    script = _write_script(tmp_path, """
        import sys
        for i in range(50):
            print(f'err line {i}', file=sys.stderr)
        sys.exit(0)
    """)
    gh = FakeGitHubClient()

    run_id = await run_agent(
        engine=engine, github=gh,
        ticket_id="t4", ticket_title="loud",
        agent=_make_agent(script),
        backend_endpoint="x",
    )

    with engine.begin() as conn:
        tail = conn.execute(
            text("SELECT stderr_tail FROM agent_runs WHERE id=:id"), {"id": run_id},
        ).scalar_one()

    lines = tail.splitlines()
    assert len(lines) == 20      # STDERR_TAIL_LINES
    assert lines[-1] == "err line 49"
    assert lines[0] == "err line 30"


async def test_spawn_failure_marks_failed(tmp_path: Path) -> None:
    # Point at a script that doesn't exist; the script_path resolves to a no-op
    # because Python interprets it as a missing file at runtime, exiting non-zero.
    missing = tmp_path / "does-not-exist.py"
    gh = FakeGitHubClient()

    run_id = await run_agent(
        engine=engine, github=gh,
        ticket_id="t5", ticket_title="missing",
        agent=_make_agent(missing),
        backend_endpoint="x",
    )

    with engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM agent_runs WHERE id=:id"), {"id": run_id},
        ).scalar_one()

    # Python prints to stderr and exits with code 2 — falls into "failed".
    assert status == "failed"
    assert gh.status_calls == []
