"""Log routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.database import get_logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def read_logs(
    category: str | None = None,
    symbol: str | None = None,
    strategy: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    return {
        "logs": get_logs(
            category=category, symbol=symbol, strategy=strategy,
            search=search, limit=limit, offset=offset,
        )
    }
