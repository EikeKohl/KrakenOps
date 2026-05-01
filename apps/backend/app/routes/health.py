"""Liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "version": __version__}
