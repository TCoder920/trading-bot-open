"""Trade and position routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.database import get_positions, get_trades

router = APIRouter(prefix="/api", tags=["trades"])


@router.get("/trades")
def read_trades(limit: int = 100):
    return {"trades": get_trades(limit=limit)}


@router.get("/positions")
def read_positions(source: str | None = None):
    return {"positions": get_positions(source=source)}
