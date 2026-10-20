"""FastAPI backend for the trading bot control layer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import state
from backend.database import init_db, seed_watchlist
from backend.routes import (
    alpaca,
    backtest,
    bot,
    config,
    datasources,
    indicators,
    logs,
    orb,
    orders,
    reconciliation,
    risk,
    strategies,
    system,
    trades,
    watchlist,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    cfg = state.get_config()
    default_symbols = cfg.get("watchlist", {}).get("stocks", [])
    if default_symbols:
        seed_watchlist(default_symbols, "stocks")
    # Optionally auto-start the autonomous scheduler. Disabled by default; only starts
    # when scheduler.enabled is true (e.g. TRADING_SCHEDULER_ENABLED=true in production).
    if cfg.get("scheduler", {}).get("enabled", False):
        from backend.services.scheduler import get_scheduler

        get_scheduler().start(cfg)
    yield
    from backend.services.scheduler import get_scheduler

    get_scheduler().stop()


app = FastAPI(title="Trading Bot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config.router)
app.include_router(risk.router)
app.include_router(watchlist.router)
app.include_router(strategies.router)
app.include_router(system.router)
app.include_router(bot.router)
app.include_router(logs.router)
app.include_router(trades.router)
app.include_router(orders.router)
app.include_router(reconciliation.router)
app.include_router(orb.router)
app.include_router(backtest.router)
app.include_router(alpaca.router)
app.include_router(indicators.router)
app.include_router(datasources.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
