"""Watchlist management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.database import (
    add_watchlist_symbol,
    get_watchlist,
    insert_log,
    remove_watchlist_symbol,
)
from backend.models import WatchlistAdd, WatchlistRemove

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
def read_watchlist(asset_class: str = "stocks"):
    return {"asset_class": asset_class, "symbols": get_watchlist(asset_class)}


@router.post("")
def add_symbol(body: WatchlistAdd):
    ok = add_watchlist_symbol(body.symbol, body.asset_class)
    if not ok:
        raise HTTPException(409, f"{body.symbol} already in {body.asset_class} watchlist")
    insert_log("watchlist", f"Added {body.symbol}", symbol=body.symbol)
    return {"status": "added", "symbol": body.symbol.upper()}


@router.delete("")
def remove_symbol(body: WatchlistRemove):
    ok = remove_watchlist_symbol(body.symbol, body.asset_class)
    if not ok:
        raise HTTPException(404, f"{body.symbol} not found in {body.asset_class} watchlist")
    insert_log("watchlist", f"Removed {body.symbol}", symbol=body.symbol)
    return {"status": "removed", "symbol": body.symbol.upper()}
