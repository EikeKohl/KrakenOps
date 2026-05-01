"""Runtime configuration. Reads env vars with sensible local-first defaults."""

from __future__ import annotations

import os
from pathlib import Path

# Where SQLite + user-supplied overrides live. Default: ~/.krakenops.
KRAKENOPS_HOME = Path(os.environ.get("KRAKENOPS_HOME", Path.home() / ".krakenops"))

# DB file inside KRAKENOPS_HOME unless explicitly overridden (tests do this).
_DB_OVERRIDE = os.environ.get("KRAKENOPS_DB_PATH")
DB_PATH = Path(_DB_OVERRIDE) if _DB_OVERRIDE else KRAKENOPS_HOME / "krakenops.db"

# Path to user pricing override, if present, merged on top of bundled defaults.
PRICING_OVERRIDE_PATH = KRAKENOPS_HOME / "pricing.yaml"

# Bundled defaults shipped with the package.
PRICING_DEFAULT_PATH = Path(__file__).parent.parent / "pricing" / "default.yaml"

# Migrations directory (versioned SQL applied in lexical order at startup).
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def db_url() -> str:
    """SQLAlchemy URL for the SQLite database."""
    return f"sqlite:///{DB_PATH}"
