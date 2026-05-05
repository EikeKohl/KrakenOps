"""Subprocess orchestrator.

Spawns the user-mapped Python script for a ticket, tracks its lifecycle in
the `agent_runs` table, classifies the exit, and reports the outcome back
to GitHub via the supplied client. Exit-code semantics live in ADR 0002.

Outcomes:
  exit 0   → succeeded            → GitHub status set to "Done"
  exit 42  → needs_human_review   → GitHub status set to "Needs Human Review"
  other    → failed               → GitHub status untouched (operator-driven)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from app.config_file import AgentConfig
    from app.poller.github import GitHubClient

_log = logging.getLogger("krakenops.poller.orchestrator")

# How much of stderr we keep on the agent_runs row for postmortem.
STDERR_TAIL_LINES = 20

EXIT_NEEDS_HUMAN_REVIEW = 42

# run_id → live Process. Used by the /v1/agents/{id}/stop route to terminate
# a still-running subprocess by handle (vs raw PID, which can be reused).
RUNNING: dict[int, asyncio.subprocess.Process] = {}


def _start_run(engine: Engine, ticket_id: str, agent_name: str) -> int:
    with engine.begin() as conn:
        cur = conn.execute(
            text(
                "INSERT INTO agent_runs (ticket_id, agent_name, started_at_s, status)"
                " VALUES (:tid, :name, :ts, 'running')"
            ),
            {"tid": ticket_id, "name": agent_name, "ts": int(time.time())},
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]


def _set_pid(engine: Engine, run_id: int, pid: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_runs SET pid = :p WHERE id = :id"),
            {"p": pid, "id": run_id},
        )


def _finish_run(
    engine: Engine,
    run_id: int,
    *,
    status: str,
    exit_code: int,
    stderr_tail: str,
) -> None:
    """Update a run's terminal state. ``stopped`` is sticky — if the route
    handler already marked the run as stopped while we were awaiting the
    subprocess, don't clobber that with a derived ``failed`` outcome."""
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT status FROM agent_runs WHERE id = :id"), {"id": run_id}
        ).first()
        if existing is not None and existing[0] == "stopped":
            conn.execute(
                text(
                    "UPDATE agent_runs"
                    " SET ended_at_s = COALESCE(ended_at_s, :ts),"
                    "     exit_code = COALESCE(exit_code, :ec),"
                    "     stderr_tail = COALESCE(stderr_tail, :err)"
                    " WHERE id = :id"
                ),
                {
                    "ts": int(time.time()),
                    "ec": exit_code,
                    "err": stderr_tail,
                    "id": run_id,
                },
            )
            return
        conn.execute(
            text(
                "UPDATE agent_runs"
                " SET ended_at_s = :ts, status = :st, exit_code = :ec, stderr_tail = :err"
                " WHERE id = :id"
            ),
            {
                "ts": int(time.time()),
                "st": status,
                "ec": exit_code,
                "err": stderr_tail,
                "id": run_id,
            },
        )


def _classify(exit_code: int) -> str:
    if exit_code == 0:
        return "succeeded"
    if exit_code == EXIT_NEEDS_HUMAN_REVIEW:
        return "needs_human_review"
    return "failed"


def _gh_status_for(outcome: str) -> str | None:
    """Map an agent-run outcome to the GitHub status to set, or None for no-op."""
    return {
        "succeeded": "Done",
        "needs_human_review": "Needs Human Review",
    }.get(outcome)


def dispatch_run(
    *,
    engine: Engine,
    github: GitHubClient,
    ticket_id: str,
    ticket_title: str,
    agent: AgentConfig,
    backend_endpoint: str,
) -> asyncio.Task[int]:
    """Schedule ``run_agent`` as a fire-and-forget asyncio task.

    Used by the manual ``POST /v1/tickets/{id}/spawn`` endpoint (ADR 0003).
    The auto-spawn-on-Todo path was removed in ADR 0006.
    """
    return asyncio.create_task(
        run_agent(
            engine=engine,
            github=github,
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            agent=agent,
            backend_endpoint=backend_endpoint,
        ),
        name=f"krakenops-run-{ticket_id}",
    )


async def run_agent(
    *,
    engine: Engine,
    github: GitHubClient,
    ticket_id: str,
    ticket_title: str,
    agent: AgentConfig,
    backend_endpoint: str,
) -> int:
    """Spawn `agent` for `ticket_id`, await completion, update GitHub. Returns the run id."""
    run_id = _start_run(engine, ticket_id, agent.name)

    env = {
        **os.environ,
        **agent.env,
        "KRAKENOPS_TICKET_ID": ticket_id,
        "KRAKENOPS_TICKET_TITLE": ticket_title,
        "TENTACLE_ENDPOINT": backend_endpoint,
    }

    cmd: list[str] = ["python", str(agent.script_path), *agent.args]
    _log.info(
        "spawning agent run id=%s ticket=%s cmd=%s", run_id, ticket_id, json.dumps(cmd)
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        _log.exception("failed to spawn agent run id=%s", run_id)
        _finish_run(
            engine, run_id, status="failed", exit_code=-1, stderr_tail=f"spawn error: {e}"
        )
        return run_id

    _set_pid(engine, run_id, proc.pid)
    RUNNING[run_id] = proc

    # Drain stderr line-by-line, keeping the last STDERR_TAIL_LINES.
    stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)

    async def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        async for line in proc.stderr:
            stderr_tail.append(line.decode(errors="replace").rstrip())

    drain = asyncio.create_task(_drain_stderr())

    try:
        rc = await proc.wait()
    finally:
        await drain
        RUNNING.pop(run_id, None)

    outcome = _classify(rc)
    _finish_run(
        engine,
        run_id,
        status=outcome,
        exit_code=rc,
        stderr_tail="\n".join(stderr_tail),
    )

    gh_status = _gh_status_for(outcome)
    if gh_status:
        try:
            await github.set_status(ticket_id, gh_status)
            _log.info(
                "ticket=%s outcome=%s exit=%s → set GitHub status %r",
                ticket_id, outcome, rc, gh_status,
            )
        except Exception:
            _log.exception("failed to update GitHub status for ticket=%s", ticket_id)
    else:
        _log.warning(
            "ticket=%s outcome=%s exit=%s → leaving GitHub status untouched (operator follow-up)",
            ticket_id, outcome, rc,
        )

    return run_id
