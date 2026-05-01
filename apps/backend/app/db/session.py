"""SQLite engine + session lifecycle.

WAL mode + foreign keys are enabled per-connection. Migrations and the pricing
seed run at app startup via init_db().
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

from app.config import DB_PATH, db_url
from app.db.migrations import apply_pending_migrations
from app.db.pricing import seed_pricing

# `check_same_thread=False` lets FastAPI's thread-pooled handlers share the
# engine; SQLAlchemy serializes access via the connection pool.
engine: Engine = create_engine(
    db_url(),
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _conn_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a SQLModel session."""
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """One-shot startup: ensure the DB directory exists, apply migrations, seed pricing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    apply_pending_migrations(engine)
    seed_pricing(engine)
