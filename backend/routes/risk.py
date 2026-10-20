"""Risk settings routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.database import insert_log, log_config_change
from backend.models import RiskSettingsUpdate

router = APIRouter(prefix="/api/risk", tags=["risk"])


def _optional_float(value):
    return float(value) if value is not None else None


@router.get("/settings")
def read_risk_settings():
    cfg = state.get_config()
    settings = dict(cfg.get("risk_limits", {}))
    paper = cfg.get("paper_trading", {})
    stocks = cfg.get("stocks", {})
    settings.update({
        "assigned_capital": _optional_float(paper.get("assigned_capital")),
        "use_assigned_capital_limit": bool(paper.get("use_assigned_capital_limit", False)),
        "stock_sizing_mode": stocks.get("sizing_mode", "notional"),
        "max_stock_order_notional": _optional_float(stocks.get("max_order_notional")),
    })
    return settings


@router.patch("/settings")
def update_risk_settings(update: RiskSettingsUpdate):
    cfg = state.get_config()
    limits = cfg.get("risk_limits", {})
    paper = cfg.get("paper_trading", {})
    stocks = cfg.get("stocks", {})
    changes = {}
    for field, val in update.model_dump(exclude_none=True).items():
        if field in {"assigned_capital", "use_assigned_capital_limit"}:
            old = paper.get(field)
            paper[field] = val
            changes[field] = {"old": old, "new": val}
            log_config_change(f"paper_trading.{field}", old, val)
        elif field == "max_stock_order_notional":
            old = stocks.get("max_order_notional")
            stocks["max_order_notional"] = val
            changes[field] = {"old": old, "new": val}
            log_config_change("stocks.max_order_notional", old, val)
        else:
            old = limits.get(field)
            limits[field] = val
            changes[field] = {"old": old, "new": val}
            log_config_change(f"risk_limits.{field}", old, val)

    cfg["risk_limits"] = limits
    cfg["paper_trading"] = paper
    cfg["stocks"] = stocks
    state.save_and_reload(cfg)
    insert_log("risk", "Risk settings updated", details=changes)
    return read_risk_settings()
