"""Cost rollups."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import get_session

router = APIRouter(prefix="/v1", tags=["costs"])

_WINDOWS_NS = {
    "1h": 60 * 60 * 1_000_000_000,
    "24h": 24 * 60 * 60 * 1_000_000_000,
    "7d": 7 * 24 * 60 * 60 * 1_000_000_000,
}


@router.get("/costs")
def costs(
    session: Annotated[Session, Depends(get_session)],
    window: str = Query("24h"),
) -> dict[str, Any]:
    if window not in _WINDOWS_NS:
        raise HTTPException(400, f"window must be one of {list(_WINDOWS_NS)}")
    since_ns = time.time_ns() - _WINDOWS_NS[window]

    rows = session.exec(
        text(
            "SELECT u.model, COUNT(*) AS calls,"
            " SUM(u.input_tokens) AS input_tokens,"
            " SUM(u.output_tokens) AS output_tokens,"
            " SUM(COALESCE(u.cost_usd, 0)) AS cost_usd"
            " FROM token_usage u"
            " JOIN spans s ON s.span_id = u.span_id"
            " WHERE s.start_time_ns >= :since"
            " GROUP BY u.model"
            " ORDER BY cost_usd DESC"
        ),
        params={"since": since_ns},
    ).all()  # type: ignore[call-arg]

    by_model = [
        {
            "model": r[0],
            "calls": int(r[1]),
            "input_tokens": int(r[2] or 0),
            "output_tokens": int(r[3] or 0),
            "cost_usd": float(r[4] or 0.0),
        }
        for r in rows
    ]
    total = round(sum(m["cost_usd"] for m in by_model), 8)
    return {"window": window, "since_ns": since_ns, "total_cost_usd": total, "by_model": by_model}
