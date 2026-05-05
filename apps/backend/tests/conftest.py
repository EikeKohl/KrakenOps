"""Test setup.

Sets KRAKENOPS_HOME + KRAKENOPS_DB_PATH to a tempdir BEFORE the app modules
are imported, so config.py reads the test paths. Each test starts with the
data tables truncated; model_pricing stays seeded so cost computation works.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# --- env setup must happen before any `app` import --------------------------

_TMP = Path(tempfile.mkdtemp(prefix="krakenops-test-"))
os.environ["KRAKENOPS_HOME"] = str(_TMP)
os.environ["KRAKENOPS_DB_PATH"] = str(_TMP / "test.db")
# Disable the per-process sampler in tests — otherwise it will scan the host
# and insert real `claude` processes mid-test, racing with the unit tests for
# the `discovered_processes` table. ADR 0005 §"Allowlist config" — empty list
# disables.
os.environ["KRAKENOPS_PROCESS_ALLOWLIST"] = ""

# Now safe to import the app and its deps.
from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.main import app  # noqa: E402

# Path to the language-neutral fixtures shared with the SDK.
CONTRACT_DIR = Path(__file__).resolve().parents[3] / "tests" / "contract"


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db() -> None:
    init_db()


@pytest.fixture
def client(_bootstrap_db: None) -> Iterator[TestClient]:
    # TestClient context-managers fire startup/shutdown lifespan events.
    with TestClient(app) as c:
        yield c
    _truncate_data_tables()


@pytest.fixture
def truncate_db() -> Iterator[None]:
    """For tests that don't need the full HTTP stack but want a clean DB."""
    _truncate_data_tables()
    yield
    _truncate_data_tables()


def _truncate_data_tables() -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        # Order matters because of FKs.
        conn.execute(text("DELETE FROM token_usage"))
        conn.execute(text("DELETE FROM spans"))
        conn.execute(text("DELETE FROM traces"))
        # ADR 0005 tables (no FKs but we want a clean slate per test).
        conn.execute(text("DELETE FROM external_metrics"))
        conn.execute(text("DELETE FROM external_events"))
        conn.execute(text("DELETE FROM discovered_processes"))
        # ADR 0006 tables — delete in dependency order: workstreams →
        # agent_runs/tickets (both reference tickets / projects) → projects.
        conn.execute(text("DELETE FROM workstreams"))
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM tickets"))
        conn.execute(text("DELETE FROM projects"))


@pytest.fixture
def fixture_loader() -> Any:
    """Returns a callable that loads a contract fixture by name."""

    def _load(name: str) -> dict[str, Any]:
        return json.loads((CONTRACT_DIR / name).read_text())

    return _load
