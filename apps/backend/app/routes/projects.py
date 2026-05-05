"""GitHub Projects mirror — REST seed for the dashboard (ADR 0006).

The poller upserts ``projects`` rows on every tick; this endpoint just
returns the latest list. The dashboard hits it once on mount and then
takes live updates from the ``kanban`` WS topic (which now also carries a
``projects`` field).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import get_session

router = APIRouter(prefix="/v1", tags=["projects"])


@router.get("/projects")
def list_projects(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    rows = session.exec(  # type: ignore[call-arg]
        text(
            "SELECT id, title, owner_login, last_seen_at_s"
            " FROM projects ORDER BY title"
        )
    ).all()
    return {
        "projects": [
            {
                "id": r[0],
                "title": r[1],
                "owner_login": r[2],
                "last_seen_at_s": int(r[3]),
            }
            for r in rows
        ]
    }
