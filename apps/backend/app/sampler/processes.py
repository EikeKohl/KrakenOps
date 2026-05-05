"""Per-process sampler.

A second 1 Hz async background task that walks `psutil.process_iter`,
keeps rows in `discovered_processes` for everything matching the allowlist,
sweeps stale rows older than 1 h on every tick, and publishes the live snapshot
on the `processes` pub/sub topic.

ADR 0005 §"Allowlist config" — the allowlist is a list of case-insensitive
substrings matched against the joined cmdline. Empty list disables the
sampler. Defaults to `("claude",)`. Configured via:

  1. ``[processes] allowlist = [...]`` in ~/.krakenops/config.toml (highest)
  2. ``KRAKENOPS_PROCESS_ALLOWLIST`` env var (comma-separated)
  3. Built-in default (``claude``)

The lifespan owner cancels this task on shutdown — same pattern as the
hardware sampler.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

import psutil
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.realtime import BUS

_log = logging.getLogger("krakenops.sampler.processes")

# How long a row may stay in `discovered_processes` after we last saw the PID
# (ADR 0005 §"Consequences" — bound table growth).
_STALE_AFTER_NS = 60 * 60 * 1_000_000_000  # 1 hour


def matches_allowlist(cmdline: str, allowlist: Iterable[str]) -> bool:
    """Case-insensitive substring match: any allowlist entry inside cmdline.

    Allowlist entries are typically pre-normalized via
    :func:`app.config_file._normalize_allowlist`, but we also lower-case here
    so callers passing raw user input (e.g. tests) still get the documented
    case-insensitive semantics.
    """
    if not cmdline:
        return False
    haystack = cmdline.lower()
    return any(needle.lower() in haystack for needle in allowlist if needle)


def matches_denylist(cmdline: str, denylist: Iterable[str]) -> bool:
    """Case-insensitive substring match: any denylist entry inside cmdline."""
    if not cmdline:
        return False
    haystack = cmdline.lower()
    return any(needle.lower() in haystack for needle in denylist if needle)


def _iter_matching_processes(
    allowlist: tuple[str, ...],
    denylist: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Snapshot psutil.process_iter, filtering by allowlist.

    `psutil.NoSuchProcess` and `psutil.AccessDenied` are swallowed silently —
    these races are normal as PIDs come and go between iter and field access.
    """
    out: list[dict[str, Any]] = []
    now_ns = time.time_ns()
    for proc in psutil.process_iter(
        ["pid", "name", "cmdline", "cpu_percent", "memory_info", "create_time"]
    ):
        try:
            info = proc.info
            cmd_list = info.get("cmdline") or []
            cmdline = " ".join(cmd_list) if cmd_list else (info.get("name") or "")
            if not matches_allowlist(cmdline, allowlist):
                continue
            if denylist and matches_denylist(cmdline, denylist):
                continue
            mem = info.get("memory_info")
            rss_mb = (mem.rss / (1024 * 1024)) if mem is not None else 0.0
            create_time = info.get("create_time")
            started_at_s = float(create_time) if create_time is not None else 0.0
            out.append(
                {
                    "pid": int(info["pid"]),
                    "name": str(info.get("name") or ""),
                    "cmdline": cmdline,
                    "cpu_pct": float(info.get("cpu_percent") or 0.0),
                    "rss_mb": float(rss_mb),
                    "started_at_s": started_at_s,
                    "observed_ns": now_ns,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process disappeared mid-iteration or we lack permission — skip.
            continue
        except Exception as e:  # pragma: no cover - defensive
            _log.debug("skipping process during iter: %s", e)
            continue
    return out


def upsert_processes(engine: Engine, snapshot: list[dict[str, Any]]) -> None:
    """Upsert each row into `discovered_processes`. PID is the primary key."""
    if not snapshot:
        return
    with engine.begin() as conn:
        for row in snapshot:
            conn.execute(
                text(
                    "INSERT INTO discovered_processes"
                    " (pid, name, cmdline, last_cpu_pct, last_rss_mb,"
                    "  first_seen_ns, last_seen_ns)"
                    " VALUES (:pid, :name, :cmdline, :cpu, :rss, :seen, :seen)"
                    " ON CONFLICT(pid) DO UPDATE SET"
                    "  name = excluded.name,"
                    "  cmdline = excluded.cmdline,"
                    "  last_cpu_pct = excluded.last_cpu_pct,"
                    "  last_rss_mb = excluded.last_rss_mb,"
                    "  last_seen_ns = excluded.last_seen_ns"
                ),
                {
                    "pid": row["pid"],
                    "name": row["name"],
                    "cmdline": row["cmdline"],
                    "cpu": row["cpu_pct"],
                    "rss": row["rss_mb"],
                    "seen": row["observed_ns"],
                },
            )


def sweep_stale(engine: Engine, now_ns: int, max_age_ns: int = _STALE_AFTER_NS) -> int:
    """Drop rows whose last_seen_ns is older than `max_age_ns`. Returns rows deleted."""
    cutoff = now_ns - max_age_ns
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM discovered_processes WHERE last_seen_ns < :cutoff"),
            {"cutoff": cutoff},
        )
        # SQLAlchemy returns -1 if rowcount unsupported; SQLite supports it.
        return int(result.rowcount or 0)


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


def _live_snapshot(engine: Engine) -> list[dict[str, Any]]:
    """Read back the currently-known rows for the WS broadcast payload."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT pid, name, cmdline, last_cpu_pct, last_rss_mb,"
                " first_seen_ns, last_seen_ns"
                " FROM discovered_processes"
                " ORDER BY last_seen_ns DESC"
            )
        ).all()
    return [_row_to_dict(r) for r in rows]


async def processes_loop(
    engine: Engine,
    allowlist: tuple[str, ...],
    interval_s: float = 1.0,
    publish: Callable[[str, Any], int] = BUS.publish,
    denylist: tuple[str, ...] = (),
) -> None:
    """Run forever (until cancelled), sampling matching processes every `interval_s`.

    Empty allowlist short-circuits at startup with a single info log — the
    task exits cleanly so the lifespan-side cancel/await is still safe.
    """
    if not allowlist:
        _log.info("process sampler disabled (empty allowlist)")
        return

    _log.info(
        "process sampler started @ %.2fs interval, allowlist=%s, denylist=%s",
        interval_s,
        list(allowlist),
        list(denylist),
    )
    try:
        while True:
            snapshot = await asyncio.to_thread(
                _iter_matching_processes, allowlist, denylist
            )
            await asyncio.to_thread(upsert_processes, engine, snapshot)
            await asyncio.to_thread(sweep_stale, engine, time.time_ns())
            # Drop rows that match the (possibly newly-edited) denylist on
            # every tick so the UI reacts quickly to config tweaks.
            if denylist:
                await asyncio.to_thread(_purge_denylisted, engine, denylist)
            live = await asyncio.to_thread(_live_snapshot, engine)
            publish("processes", {"processes": live})
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _log.info("process sampler stopped")
        raise


def _purge_denylisted(engine: Engine, denylist: tuple[str, ...]) -> int:
    if not denylist:
        return 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT pid, cmdline FROM discovered_processes"
            )
        ).all()
        to_delete = [r[0] for r in rows if matches_denylist(r[1] or "", denylist)]
        if not to_delete:
            return 0
        # SQLite's `DELETE … WHERE pid IN (...)` with a parameter list — bind each.
        placeholders = ",".join(f":p{i}" for i in range(len(to_delete)))
        params = {f"p{i}": pid for i, pid in enumerate(to_delete)}
        result = conn.execute(
            text(f"DELETE FROM discovered_processes WHERE pid IN ({placeholders})"),
            params,
        )
        return int(result.rowcount or 0)


def start(
    engine: Engine,
    allowlist: tuple[str, ...],
    interval_s: float = 1.0,
    denylist: tuple[str, ...] = (),
) -> asyncio.Task[None]:
    """Spawn the per-process sampler as a background task."""
    return asyncio.create_task(
        processes_loop(engine, allowlist, interval_s=interval_s, denylist=denylist),
        name="krakenops-processes-sampler",
    )
