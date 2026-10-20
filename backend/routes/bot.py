"""Bot status and control routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.database import (
    get_active_strategy,
    get_daily_ledger,
    get_positions,
    get_trades,
    insert_log,
    reset_daily_ledger,
)
from backend.services.broker_factory import get_broker_service
from backend.services.scheduler import get_scheduler
from lumibot.custom_config.risk_engine import RiskEngine
from lumibot.custom_strategies.session import SessionClock, SessionWindows

router = APIRouter(prefix="/api/bot", tags=["bot"])


def _kill_switch_snapshot(cfg: dict) -> dict:
    """Recompute kill-switch state from the persisted (SQLite) ledger."""
    clock = SessionClock(SessionWindows.from_config(cfg.get("stocks_in_play_orb_v1", {})))
    ledger = get_daily_ledger(clock.session_day_str())
    risk = RiskEngine(cfg, clock=clock)
    risk.sync_ledger(
        trade_count=ledger.get("trade_count", 0),
        realised_loss=ledger.get("realised_loss", 0.0),
        open_positions=ledger.get("open_positions", 0),
        trade_date=clock.session_day_str(),
    )
    return {
        "kill_switch_active": risk.kill_switch_active,
        "kill_switch_reasons": risk.kill_switch_reasons,
        "session": clock.session(),
        "session_day": clock.session_day_str(),
    }


def _running_state(cfg: dict) -> str:
    mode = cfg.get("trading_mode", "simulation")
    return "running_paper" if mode == "paper" else ("running_live" if mode == "live" else "running_simulation")


@router.get("/status")
def bot_status():
    cfg = state.get_config()
    ledger = get_daily_ledger()
    active = get_active_strategy()
    positions = get_positions()
    trades_today = get_trades(limit=200)
    broker = get_broker_service(cfg)
    broker_status = broker.broker_status()
    sched = get_scheduler().status()
    kill = _kill_switch_snapshot(cfg)
    return {
        "bot_state": state.bot_state,
        "scheduler": sched.to_dict(),
        "active_broker": cfg.get("active_broker", "alpaca"),
        "active_data_provider": cfg.get("active_data_provider", "alpaca"),
        "trading_mode": cfg.get("trading_mode", "simulation"),
        "live_trading_enabled": cfg.get("live_trading_enabled", False),
        "allow_extended_hours": cfg.get("alpaca", {}).get("allow_extended_hours", False),
        "session": kill["session"],
        "session_day": kill["session_day"],
        "kill_switch_active": kill["kill_switch_active"],
        "kill_switch_reasons": kill["kill_switch_reasons"],
        "default_asset_class": cfg.get("default_asset_class", "stocks"),
        "active_asset_classes": cfg.get("active_asset_classes", ["stocks"]),
        "active_strategy": active["name"] if active else None,
        "daily_pnl": sum(t.get("pnl") or 0 for t in trades_today),
        "trades_today": ledger.get("trade_count", 0),
        "max_daily_loss": cfg.get("risk_limits", {}).get("max_daily_loss", 0),
        "open_positions": len(positions),
        "alpaca_enabled": cfg.get("alpaca", {}).get("enabled", True),
        "alpaca_credentials_configured": broker_status["credentials"]["configured"],
        "paper": broker_status["paper"],
        "asset_classes": broker.asset_classes(),
    }


@router.post("/start")
def start_bot():
    cfg = state.get_config()
    sched = get_scheduler().start(cfg)
    state.bot_state = _running_state(cfg)
    insert_log("bot", f"Bot started ({cfg.get('trading_mode', 'simulation')})",
               details={"scheduler": sched.state})
    return {"status": state.bot_state, "scheduler": sched.to_dict()}


@router.post("/pause")
def pause_bot():
    sched = get_scheduler().pause()
    state.bot_state = "paused"
    insert_log("bot", "Bot paused")
    return {"status": state.bot_state, "scheduler": sched.to_dict()}


@router.post("/resume")
def resume_bot():
    cfg = state.get_config()
    sched = get_scheduler().resume(cfg)
    state.bot_state = _running_state(cfg)
    insert_log("bot", "Bot resumed")
    return {"status": state.bot_state, "scheduler": sched.to_dict()}


@router.post("/stop")
def stop_bot():
    sched = get_scheduler().stop()
    state.bot_state = "stopped"
    insert_log("bot", "Bot stopped")
    return {"status": state.bot_state, "scheduler": sched.to_dict()}


@router.post("/tick")
def manual_tick():
    """Run a single autonomous tick synchronously (diagnostics / manual stepping)."""
    cfg = state.get_config()
    result = get_scheduler().run_once(cfg)
    return result


@router.get("/ledger")
def read_ledger():
    return get_daily_ledger()


@router.post("/ledger/reset")
def do_reset_ledger():
    result = reset_daily_ledger()
    insert_log("bot", "Daily ledger reset")
    return result
