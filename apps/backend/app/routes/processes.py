"""Discovered-processes REST seed + kill command (ADR 0005).

GET /v1/processes — latest snapshot from ``discovered_processes``, sorted
``last_seen_ns DESC``. The dashboard hits this once on mount, then takes
live updates from the ``processes`` WS topic.

POST /v1/processes/{pid}/kill — best-effort SIGTERM (then SIGKILL if needed)
for a discovered process. Only PIDs the sampler currently tracks are
killable — this prevents the dashboard from being used to murder arbitrary
host processes.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db import engine
from app.db.session import get_session

_log = logging.getLogger("krakenops.routes.processes")

router = APIRouter(prefix="/v1", tags=["processes"])


@router.get("/processes")
def list_processes(
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    rows = session.exec(
        text(
            "SELECT pid, name, cmdline, last_cpu_pct, last_rss_mb,"
            " first_seen_ns, last_seen_ns"
            " FROM discovered_processes"
            " ORDER BY last_seen_ns DESC LIMIT :limit"
        ),
        params={"limit": limit},
    ).all()  # type: ignore[call-arg]
    return {"processes": [_row_to_dict(r) for r in rows]}


@router.post("/processes/{pid}/kill")
def kill_process(pid: int) -> dict[str, Any]:
    """Best-effort terminate a discovered process. Refuses unknown PIDs."""
    if pid <= 0:
        raise HTTPException(400, "invalid pid")
    if pid == os.getpid():
        # Self-preservation: never let the dashboard kill the backend.
        raise HTTPException(400, "refusing to kill the backend process itself")

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT pid, name, cmdline FROM discovered_processes WHERE pid = :pid"
            ),
            {"pid": pid},
        ).first()
    if row is None:
        raise HTTPException(404, "pid is not in the discovered list")

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        # Process already gone — sweep the row so the UI stops showing it.
        _delete_row(pid)
        return {"killed": True, "pid": pid, "method": "already_exited"}

    method = "terminate"
    try:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except psutil.TimeoutExpired:
            proc.kill()
            method = "kill"
            try:
                proc.wait(timeout=1.0)
            except psutil.TimeoutExpired:
                _log.warning("kill pid=%s did not exit within grace window", pid)
    except psutil.NoSuchProcess:
        method = "already_exited"
    except psutil.AccessDenied as e:
        raise HTTPException(403, f"insufficient permissions to signal pid {pid}") from e
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(500, f"kill failed: {e}") from e

    _delete_row(pid)
    return {"killed": True, "pid": pid, "method": method}


def _delete_row(pid: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM discovered_processes WHERE pid = :pid"),
            {"pid": pid},
        )


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "pid": int(row[0]),
        "name": row[1],
        "cmdline": row[2],
        "cpu_pct": float(row[3]),
        "rss_mb": float(row[4]),
        "first_seen_ns": int(row[5]),
        "last_seen_ns": int(row[6]),
    }
