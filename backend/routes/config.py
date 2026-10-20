"""Configuration management routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend import state
from backend.config_validation import (
    apply_config_updates,
    validate_config_batch,
    validate_config_update,
    validate_live_trading,
)
from backend.database import insert_log, log_config_change
from backend.models import ConfigBatchUpdate, ConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

FLAT_KEYS = {
    "active_broker",
    "active_data_provider",
    "trading_mode",
    "live_trading_enabled",
    "require_order_review",
    "default_data_source",
    "default_asset_class",
    "active_asset_classes",
}


def _apply_key(cfg: dict, key: str, value: object) -> None:
    if key in FLAT_KEYS:
        cfg[key] = value
    elif key.startswith("alpaca."):
        sub = key.split(".", 1)[1]
        cfg.setdefault("alpaca", {})[sub] = value
    elif key.startswith("risk_limits."):
        sub = key.split(".", 1)[1]
        cfg.setdefault("risk_limits", {})[sub] = value
    elif key.startswith("paper_trading."):
        sub = key.split(".", 1)[1]
        cfg.setdefault("paper_trading", {})[sub] = value
    elif key.startswith("ui."):
        sub = key.split(".", 1)[1]
        cfg.setdefault("ui", {})[sub] = value
    elif key.startswith(("stocks.", "options.", "crypto.")):
        group, sub = key.split(".", 1)
        cfg.setdefault(group, {})[sub] = value
    else:
        cfg[key] = value


def _log_config_event(message: str, *, level: str = "info", details: dict | None = None) -> None:
    insert_log("config", message, level=level, details=details)
    if level == "error":
        logger.warning(message)
    else:
        logger.info(message)


@router.get("")
def read_config():
    return state.get_config()


@router.patch("")
def update_config(update: ConfigUpdate):
    cfg = state.get_config()
    old = cfg.get(update.key)
    if update.key.startswith("alpaca."):
        sub = update.key.split(".", 1)[1]
        old = cfg.get("alpaca", {}).get(sub)
    elif update.key.startswith("paper_trading."):
        sub = update.key.split(".", 1)[1]
        old = cfg.get("paper_trading", {}).get(sub)

    ok, err = validate_config_update(cfg, update.key, update.value)
    if not ok:
        _log_config_event(
            f"Config update rejected: {update.key}={update.value!r} — {err}",
            level="error",
            details={"key": update.key, "value": update.value, "error": err},
        )
        raise HTTPException(400, err)

    _apply_key(cfg, update.key, update.value)
    log_config_change(update.key, old, update.value)
    state.save_and_reload(cfg)
    _log_config_event(
        f"Updated {update.key}: {old!r} → {update.value!r}",
        details={"key": update.key, "old": old, "new": update.value},
    )
    return {"status": "ok", "key": update.key, "value": update.value}


@router.patch("/batch")
def update_config_batch(body: ConfigBatchUpdate):
    cfg = state.get_config()
    errors = validate_config_batch(cfg, body.updates)

    if errors:
        _log_config_event(
            "Batch config update rejected",
            level="error",
            details={"errors": errors, "keys": list(body.updates.keys())},
        )
        raise HTTPException(400, {"errors": errors})

    changed: list[dict] = []
    for key, value in body.updates.items():
        old = cfg.get(key)
        if key.startswith("alpaca."):
            old = cfg.get("alpaca", {}).get(key.split(".", 1)[1])
        elif key.startswith("paper_trading."):
            old = cfg.get("paper_trading", {}).get(key.split(".", 1)[1])
        elif key.startswith(("stocks.", "options.", "crypto.")):
            group, sub = key.split(".", 1)
            old = cfg.get(group, {}).get(sub)
        if old != value:
            changed.append({"key": key, "old": old, "new": value})
        _apply_key(cfg, key, value)
        log_config_change(key, old, value)

    state.save_and_reload(cfg)
    _log_config_event(
        "Batch config update saved",
        details={"keys": list(body.updates.keys()), "changed": changed},
    )
    return {"status": "ok", "config": state.get_config()}


@router.post("/validate-draft")
def validate_draft(body: ConfigBatchUpdate):
    """Validate unsaved Settings draft against current config + merged updates."""
    cfg = state.get_config()
    merged = apply_config_updates(cfg, body.updates)
    errors = validate_config_batch(cfg, body.updates)
    ok, live_errors = validate_live_trading(merged)
    wants_live = body.updates.get("live_trading_enabled", cfg.get("live_trading_enabled", False))
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "live_trading_requested": bool(wants_live),
        "live_trading_ready": ok if wants_live else True,
        "live_trading_errors": live_errors if wants_live else [],
    }


@router.get("/validation")
def config_validation():
    cfg = state.get_config()
    ok, errors = validate_live_trading(cfg)
    return {
        "live_trading_ready": ok,
        "errors": errors,
        "live_trading_enabled": cfg.get("live_trading_enabled", False),
    }


@router.post("/reload")
def reload_config():
    state.reload_config()
    _log_config_event("Configuration reloaded from disk")
    return {"status": "reloaded", "config": state.get_config()}
