"""System readiness and operations routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.config_validation import validate_trading_mode
from backend.database import backup_database, get_schema_migrations, insert_log
from backend.services.broker_factory import get_broker_service

router = APIRouter(prefix="/api/system", tags=["system"])


def _positive(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


@router.get("/readiness")
def system_readiness():
    cfg = state.get_config()
    mode = cfg.get("trading_mode", "simulation")
    broker = get_broker_service(cfg)
    credentials = broker.credential_status()
    paper_ok, paper_errors = validate_trading_mode(cfg, "paper", "stocks")
    live_ok, live_errors = validate_trading_mode(cfg, "live", "stocks")
    migrations = get_schema_migrations()

    risk = cfg.get("risk_limits", {})
    paper_trading = cfg.get("paper_trading", {})
    stocks = cfg.get("stocks", {})
    checks: list[dict] = []

    def add(key: str, ok: bool, message: str, severity: str = "error"):
        checks.append({"key": key, "ok": ok, "message": message, "severity": severity})

    add("database_migrations", len(migrations) >= 3, f"{len(migrations)} schema migrations applied")
    add("active_broker", cfg.get("active_broker") == "alpaca", "Active broker must be Alpaca")
    add("active_data_provider", cfg.get("active_data_provider") == "alpaca", "Active data provider must be Alpaca")
    add("alpaca_credentials", bool(credentials.get("configured")), "Alpaca credentials must be configured for broker-connected trading")
    add("paper_stocks_ready", paper_ok, "; ".join(paper_errors) if paper_errors else "Paper stock trading gates pass")
    add("live_trading_disabled_by_default", not bool(cfg.get("live_trading_enabled")), "Live trading switch is currently off", "warning")
    add("max_dollars_per_trade", _positive(risk.get("max_dollars_per_trade")), "max_dollars_per_trade must be positive")
    add("max_daily_loss", _positive(risk.get("max_daily_loss")), "max_daily_loss must be positive")
    add("max_open_positions", _positive(risk.get("max_open_positions")), "max_open_positions must be positive")
    add("stock_sizing_mode", stocks.get("sizing_mode") == "notional", "Default stock sizing mode is notional")

    wants_live = mode == "live" or bool(cfg.get("live_trading_enabled"))
    if wants_live:
        add("live_stocks_ready", live_ok, "; ".join(live_errors) if live_errors else "Live stock gates pass")
        add(
            "assigned_capital_optional",
            True,
            "Assigned capital is optional; unset means use Alpaca available capital",
            "warning",
        )
    else:
        add(
            "assigned_capital_configured",
            True,
            "Assigned-capital limit is optional; leave unset to use Alpaca available capital",
            "warning",
        )

    errors = [c for c in checks if not c["ok"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warning"]
    return {
        "ready_for_paper": paper_ok and bool(credentials.get("configured")),
        "ready_for_live": len(errors) == 0 and live_ok and wants_live,
        "trading_mode": mode,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "schema_migrations": migrations,
    }


@router.post("/backup")
def create_backup():
    backup = backup_database()
    insert_log("system", "Database backup created", details=backup)
    return {"status": "ok", "backup": backup}
