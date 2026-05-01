"""Agent runs: history list + stop command. See ADR 0003."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db import engine as engine_singleton
from app.db.session import get_session
from app.poller import orchestrator

_log = logging.getLogger("krakenops.routes.agents")

router = APIRouter(prefix="/v1", tags=["agents"])


# Grace window between SIGTERM and SIGKILL.
_STOP_GRACE_S = 3.0


@router.get("/agents")
def list_agent_runs(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = Query(
        None, description="running | succeeded | needs_human_review | failed | stopped"
    ),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    where = ""
    params: dict[str, Any] = {"limit": limit}
    if status:
        where = "WHERE status = :status"
        params["status"] = status
    rows = session.exec(  # type: ignore[call-arg]
        text(
            "SELECT id, ticket_id, agent_name, pid, started_at_s, ended_at_s,"
            " status, exit_code, stderr_tail"
            f" FROM agent_runs {where}"
            " ORDER BY started_at_s DESC LIMIT :limit"
        ),
        params=params,
    ).all()
    return {
        "runs": [
            {
                "id": r[0],
                "ticket_id": r[1],
                "agent_name": r[2],
                "pid": r[3],
                "started_at_s": r[4],
                "ended_at_s": r[5],
                "status": r[6],
                "exit_code": r[7],
                "stderr_tail": r[8],
            }
            for r in rows
        ]
    }


@router.post("/agents/{run_id}/stop")
async def stop_agent_run(run_id: int) -> dict[str, Any]:
    """Terminate a running agent_run. See ADR 0003."""
    with engine_singleton.begin() as conn:
        row = conn.execute(
            text("SELECT status FROM agent_runs WHERE id = :id"), {"id": run_id},
        ).first()
        if row is None:
            raise HTTPException(404, "agent run not found")
        if row[0] != "running":
            raise HTTPException(409, f"run is in {row[0]!r}, not 'running'")

        # Mark "stopped" *before* signaling so the orchestrator's exit handler
        # sees the sticky status and doesn't reclassify as 'failed'.
        conn.execute(
            text(
                "UPDATE agent_runs"
                " SET status = 'stopped', ended_at_s = :ts, exit_code = -15"
                " WHERE id = :id"
            ),
            {"ts": int(time.time()), "id": run_id},
        )

    proc = orchestrator.RUNNING.get(run_id)
    if proc is None:
        # Process already exited between status check and now — race window.
        # The DB row is correctly marked; nothing else to do.
        _log.info("stop run_id=%s: process already exited", run_id)
        return {"stopped": True}

    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=_STOP_GRACE_S)
    except TimeoutError:
        _log.warning("stop run_id=%s: SIGTERM grace expired, sending SIGKILL", run_id)
        proc.kill()
        with __import__("contextlib").suppress(Exception):
            await proc.wait()

    return {"stopped": True}
