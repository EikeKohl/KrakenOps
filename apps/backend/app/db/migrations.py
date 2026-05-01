"""Tiny in-process migration runner.

Reads `migrations/*.sql` in lexical order, applies any whose integer prefix
isn't yet recorded in `schema_migrations`. Each file runs in a single
transaction; failures roll back. We don't need Alembic for this scope —
SQLite + monotonic SQL files is plenty.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import MIGRATIONS_DIR

_log = logging.getLogger("krakenops.migrations")
_VERSION_RE = re.compile(r"^(\d+)_")


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in sorted(migrations_dir.glob("*.sql")):
        m = _VERSION_RE.match(p.name)
        if not m:
            raise RuntimeError(f"migration filename must start with NNN_: {p.name}")
        out.append((int(m.group(1)), p))
    return out


def _strip_line_comments(sql: str) -> str:
    """Drop ``-- ...`` line comments before splitting on ``;`` so semicolons in
    comments don't fool the splitter."""
    lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        lines.append(line[:idx] if idx != -1 else line)
    return "\n".join(lines)


def _ensure_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INTEGER PRIMARY KEY,"
                " applied_at_s INTEGER NOT NULL"
                ") STRICT"
            )
        )


def _applied_versions(engine: Engine) -> set[int]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).all()
    return {r[0] for r in rows}


def apply_pending_migrations(engine: Engine, migrations_dir: Path | None = None) -> list[int]:
    """Apply any unapplied migration files. Returns the versions actually applied."""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    _ensure_table(engine)
    applied = _applied_versions(engine)
    pending = [(v, p) for v, p in _discover(migrations_dir) if v not in applied]

    newly: list[int] = []
    for version, path in pending:
        sql = _strip_line_comments(path.read_text())
        with engine.begin() as conn:
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    conn.execute(text(stmt))
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at_s) VALUES (:v, :t)"),
                {"v": version, "t": int(time.time())},
            )
        _log.info("applied migration %03d (%s)", version, path.name)
        newly.append(version)

    return newly
