"""Migration runner: idempotent, applies version 001."""

from __future__ import annotations

from sqlalchemy import text

from app.db import engine
from app.db.migrations import apply_pending_migrations


def test_initial_migration_applied() -> None:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).all()
    versions = {r[0] for r in rows}
    assert 1 in versions


def test_apply_is_idempotent() -> None:
    # init_db has already run via session-scoped autouse fixture; calling again must be a no-op.
    newly = apply_pending_migrations(engine)
    assert newly == []


def test_expected_tables_exist() -> None:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ).all()
    names = {r[0] for r in rows}
    for expected in ("traces", "spans", "token_usage", "model_pricing", "schema_migrations"):
        assert expected in names
