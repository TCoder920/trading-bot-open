"""Alpaca-only configuration validation."""

from __future__ import annotations

import os

TRADING_MODES = {"simulation", "paper", "live"}
ASSET_CLASSES = {"stocks", "options", "crypto"}


def alpaca_credential_status(cfg: dict) -> dict:
    alpaca = cfg.get("alpaca", {})
    mode = cfg.get("trading_mode", "simulation")
    key_var = alpaca.get("api_key_env_var", "ALPACA_API_KEY")
    secret_var = alpaca.get("api_secret_env_var", "ALPACA_API_SECRET")
    oauth_var = alpaca.get("oauth_token_env_var", "ALPACA_OAUTH_TOKEN")
    paper_var = alpaca.get("is_paper_env_var", "ALPACA_IS_PAPER")

    api_key_present = bool(os.environ.get(key_var))
    api_secret_present = bool(os.environ.get(secret_var))
    oauth_present = bool(os.environ.get(oauth_var))
    paper_key_present = bool(os.environ.get("ALPACA_PAPER_API_KEY"))
    paper_secret_present = bool(os.environ.get("ALPACA_PAPER_API_SECRET"))
    live_key_present = bool(os.environ.get("ALPACA_LIVE_API_KEY"))
    live_secret_present = bool(os.environ.get("ALPACA_LIVE_API_SECRET"))

    if mode == "live":
        selected_key_present = live_key_present or api_key_present
        selected_secret_present = live_secret_present or api_secret_present
    elif mode == "paper":
        selected_key_present = paper_key_present or api_key_present
        selected_secret_present = paper_secret_present or api_secret_present
    else:
        selected_key_present = api_key_present or paper_key_present or live_key_present
        selected_secret_present = api_secret_present or paper_secret_present or live_secret_present
    configured = oauth_present or (selected_key_present and selected_secret_present)

    return {
        "configured": configured,
        "selected_mode": mode,
        "api_key_present": api_key_present,
        "api_secret_present": api_secret_present,
        "paper_api_key_present": paper_key_present,
        "paper_api_secret_present": paper_secret_present,
        "live_api_key_present": live_key_present,
        "live_api_secret_present": live_secret_present,
        "selected_key_present": selected_key_present,
        "selected_secret_present": selected_secret_present,
        "oauth_token_present": oauth_present,
        "is_paper_env_present": bool(os.environ.get(paper_var)),
        "api_key_env_var": key_var,
        "api_secret_env_var": secret_var,
        "oauth_token_env_var": oauth_var,
        "is_paper_env_var": paper_var,
    }


def validate_asset_class(cfg: dict, asset_class: str, mode: str | None = None) -> list[str]:
    errors: list[str] = []
    mode = mode or cfg.get("trading_mode", "simulation")
    if asset_class not in ASSET_CLASSES:
        return [f"Unsupported asset class: {asset_class}."]
    if asset_class not in cfg.get("active_asset_classes", []):
        errors.append(f"{asset_class} is not in active_asset_classes.")

    block = cfg.get(asset_class, {})
    if not block.get("enabled", False):
        errors.append(f"{asset_class} is disabled.")
    if asset_class in {"options", "crypto"}:
        if block.get("require_explicit_enablement", True) and not block.get("explicit_enablement", False):
            errors.append(f"{asset_class} requires explicit enablement before broker-connected trading.")
    if asset_class == "options" and mode in {"paper", "live"} and not block.get("account_approved", False):
        status = block.get("approval_status", "pending")
        errors.append(f"Options account approval is {status}; broker-connected options trading is blocked.")
    if mode == "paper" and not block.get("paper_enabled", False):
        errors.append(f"{asset_class} paper trading is disabled.")
    if mode == "live" and not block.get("live_enabled", False):
        errors.append(f"{asset_class} live trading is disabled.")
    return errors


def validate_trading_mode(cfg: dict, mode: str | None = None, asset_class: str | None = None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    mode = mode or cfg.get("trading_mode", "simulation")
    asset_class = asset_class or cfg.get("default_asset_class", "stocks")

    if mode not in TRADING_MODES:
        errors.append("trading_mode must be simulation, paper, or live.")
        return False, errors

    if cfg.get("active_broker") != "alpaca":
        errors.append("Active broker must be Alpaca.")
    if cfg.get("active_data_provider") != "alpaca":
        errors.append("Active data provider must be Alpaca.")
    if not cfg.get("alpaca", {}).get("enabled", False):
        errors.append("Alpaca must be enabled.")
    errors.extend(validate_asset_class(cfg, asset_class, mode))

    if mode == "simulation":
        return len(errors) == 0, errors

    creds = alpaca_credential_status(cfg)
    mock_paper = mode == "paper" and cfg.get("alpaca", {}).get("mock_paper_submission", False)
    if not creds["configured"] and not mock_paper:
        errors.append(
            "Alpaca credentials are not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET, "
            "or set ALPACA_OAUTH_TOKEN."
        )

    if mode == "live":
        if not cfg.get("live_trading_enabled", False):
            errors.append("live_trading_enabled must be true for live mode.")
        if cfg.get("alpaca", {}).get("paper", True):
            errors.append("Alpaca paper flag must be false for live mode.")

    return len(errors) == 0, errors


def validate_extended_hours_config(cfg: dict) -> list[str]:
    """Validate extended-hours + scheduler settings (Alpaca-only constraints)."""
    errors: list[str] = []
    alpaca = cfg.get("alpaca", {})

    if not isinstance(alpaca.get("allow_extended_hours", False), bool):
        errors.append("alpaca.allow_extended_hours must be a boolean.")

    feed = str(alpaca.get("extended_hours_data_feed", "sip")).lower()
    if feed not in {"iex", "sip"}:
        errors.append("alpaca.extended_hours_data_feed must be 'iex' or 'sip'.")
    if alpaca.get("allow_extended_hours") and feed == "iex":
        # Not fatal, but the iex feed is sparse outside RTH; warn loudly.
        errors.append(
            "alpaca.extended_hours_data_feed should be 'sip' when allow_extended_hours is true "
            "(iex has sparse pre/post-market data)."
        )

    offset = alpaca.get("marketable_limit_offset_pct", 0.2)
    try:
        offset_val = float(offset)
        if offset_val < 0 or offset_val > 10:
            errors.append("alpaca.marketable_limit_offset_pct must be between 0 and 10.")
    except (TypeError, ValueError):
        errors.append("alpaca.marketable_limit_offset_pct must be a number.")

    scheduler = cfg.get("scheduler", {})
    interval = scheduler.get("interval_seconds", 60)
    try:
        if int(interval) < 1:
            errors.append("scheduler.interval_seconds must be >= 1.")
    except (TypeError, ValueError):
        errors.append("scheduler.interval_seconds must be an integer.")

    orb = cfg.get("stocks_in_play_orb_v1", {})
    ext_mode = str(orb.get("extended_hours_signals", "rth_only")).lower()
    if ext_mode not in {"rth_only", "extended"}:
        errors.append("stocks_in_play_orb_v1.extended_hours_signals must be 'rth_only' or 'extended'.")
    return errors


def validate_live_trading(cfg: dict) -> tuple[bool, list[str]]:
    """Validate the explicit live-trading gate."""
    if not cfg.get("live_trading_enabled", False):
        return True, []
    return validate_trading_mode(cfg, "live", cfg.get("default_asset_class", "stocks"))


def apply_config_updates(cfg: dict, updates: dict[str, object]) -> dict:
    """Return a copy of cfg with all updates applied."""
    import copy

    merged = copy.deepcopy(cfg)
    flat_keys = {
        "active_broker",
        "active_data_provider",
        "trading_mode",
        "live_trading_enabled",
        "require_order_review",
        "default_data_source",
        "default_asset_class",
    }
    for key, value in updates.items():
        if key in flat_keys:
            merged[key] = value
        elif key.startswith("alpaca."):
            sub = key.split(".", 1)[1]
            merged.setdefault("alpaca", {})[sub] = value
        elif key.startswith("risk_limits."):
            sub = key.split(".", 1)[1]
            merged.setdefault("risk_limits", {})[sub] = value
        elif key.startswith("paper_trading."):
            sub = key.split(".", 1)[1]
            merged.setdefault("paper_trading", {})[sub] = value
        elif key.startswith("ui."):
            sub = key.split(".", 1)[1]
            merged.setdefault("ui", {})[sub] = value
        elif key.startswith("scheduler."):
            sub = key.split(".", 1)[1]
            merged.setdefault("scheduler", {})[sub] = value
        elif key.startswith("stocks_in_play_orb_v1."):
            sub = key.split(".", 1)[1]
            merged.setdefault("stocks_in_play_orb_v1", {})[sub] = value
        elif key.startswith(("stocks.", "options.", "crypto.")):
            group, sub = key.split(".", 1)
            merged.setdefault(group, {})[sub] = value
        elif key == "active_asset_classes":
            merged[key] = value
        else:
            merged[key] = value
    return merged


def validate_config_batch(cfg: dict, updates: dict[str, object]) -> list[str]:
    """Validate a batch of config updates against the merged draft."""
    merged = apply_config_updates(cfg, updates)
    errors: list[str] = []

    if merged.get("active_broker") != "alpaca":
        errors.append("Only Alpaca is supported as active_broker.")
    if merged.get("active_data_provider") != "alpaca":
        errors.append("Only Alpaca is supported as active_data_provider.")
    if merged.get("default_data_source") != "alpaca":
        errors.append("Only Alpaca is supported as default_data_source.")
    if merged.get("trading_mode") not in TRADING_MODES:
        errors.append("trading_mode must be simulation, paper, or live.")
    if merged.get("default_asset_class") not in ASSET_CLASSES:
        errors.append("default_asset_class must be stocks, options, or crypto.")

    if merged.get("live_trading_enabled") or merged.get("trading_mode") == "live":
        ok, live_errors = validate_trading_mode(merged, "live", merged.get("default_asset_class", "stocks"))
        if not ok:
            errors.extend(live_errors)
    elif merged.get("trading_mode") == "paper":
        ok, paper_errors = validate_trading_mode(merged, "paper", merged.get("default_asset_class", "stocks"))
        if not ok:
            errors.extend(paper_errors)

    errors.extend(validate_extended_hours_config(merged))

    for key, value in updates.items():
        if key in {
            "active_broker",
            "active_data_provider",
            "default_data_source",
            "trading_mode",
            "live_trading_enabled",
            "default_asset_class",
        } or key.startswith(("alpaca.", "stocks.", "options.", "crypto.", "paper_trading.", "risk_limits.")):
            continue
        continue

    return _dedupe(errors)


def validate_config_update(cfg: dict, key: str, value: object) -> tuple[bool, str | None]:
    test_cfg = apply_config_updates(cfg, {key: value})
    if key in {"active_broker", "active_data_provider", "default_data_source", "trading_mode", "default_asset_class"}:
        errors = validate_config_batch(cfg, {key: value})
        if errors:
            return False, "; ".join(errors)
    if test_cfg.get("live_trading_enabled"):
        ok, live_errors = validate_live_trading(test_cfg)
        if not ok:
            return False, "; ".join(live_errors)
    return True, None


def _dedupe(errors: list[str]) -> list[str]:
    seen = set()
    result = []
    for error in errors:
        if error not in seen:
            seen.add(error)
            result.append(error)
    return result
