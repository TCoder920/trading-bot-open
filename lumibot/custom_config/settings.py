import os
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _CONFIG_DIR / "defaults.yaml"
_USER_OVERRIDE = _CONFIG_DIR / "user_config.yaml"

_cached_config: dict | None = None


def load_config(override_path: str | None = None) -> dict:
    """Load configuration from defaults, then overlay user overrides."""
    global _cached_config

    _load_repo_env()

    with open(_DEFAULT_CONFIG) as f:
        config = yaml.safe_load(f)

    override = Path(override_path) if override_path else _USER_OVERRIDE
    if override.exists():
        with open(override) as f:
            user = yaml.safe_load(f) or {}
        config = _deep_merge(config, user)

    env_live = os.environ.get("TRADING_LIVE_ENABLED")
    if env_live is not None:
        config["live_trading_enabled"] = env_live.lower() in ("true", "1", "yes")
    env_live = os.environ.get("LIVE_TRADING_ENABLED", env_live)
    if env_live is not None:
        config["live_trading_enabled"] = env_live.lower() in ("true", "1", "yes")
    env_mode = os.environ.get("TRADING_MODE")
    if env_mode is not None:
        config["trading_mode"] = env_mode.lower()
    env_feed = os.environ.get("ALPACA_DATA_FEED")
    if env_feed:
        config.setdefault("alpaca", {})["data_feed"] = env_feed.lower()
    env_paper = os.environ.get("ALPACA_IS_PAPER")
    if env_paper is not None:
        config.setdefault("alpaca", {})["paper"] = env_paper.lower() in ("true", "1", "yes")
    env_mock_paper = os.environ.get("ALPACA_MOCK_PAPER_SUBMISSION")
    if env_mock_paper is not None:
        config.setdefault("alpaca", {})["mock_paper_submission"] = env_mock_paper.lower() in ("true", "1", "yes")
    env_ext_hours = os.environ.get("ALPACA_ALLOW_EXTENDED_HOURS")
    if env_ext_hours is not None:
        config.setdefault("alpaca", {})["allow_extended_hours"] = env_ext_hours.lower() in ("true", "1", "yes")
    env_ext_feed = os.environ.get("ALPACA_EXTENDED_HOURS_DATA_FEED")
    if env_ext_feed:
        config.setdefault("alpaca", {})["extended_hours_data_feed"] = env_ext_feed.lower()
    env_sched = os.environ.get("TRADING_SCHEDULER_ENABLED")
    if env_sched is not None:
        config.setdefault("scheduler", {})["enabled"] = env_sched.lower() in ("true", "1", "yes")
    env_sched_interval = os.environ.get("TRADING_SCHEDULER_INTERVAL_SECONDS")
    if env_sched_interval:
        try:
            config.setdefault("scheduler", {})["interval_seconds"] = int(env_sched_interval)
        except ValueError:
            pass
    env_options_live = os.environ.get("OPTIONS_LIVE_ENABLED")
    if env_options_live is not None:
        config.setdefault("options", {})["live_enabled"] = env_options_live.lower() in ("true", "1", "yes")
    env_options_paper = os.environ.get("OPTIONS_PAPER_ENABLED")
    if env_options_paper is not None:
        config.setdefault("options", {})["paper_enabled"] = env_options_paper.lower() in ("true", "1", "yes")
    env_options_explicit = os.environ.get("OPTIONS_EXPLICIT_ENABLEMENT")
    if env_options_explicit is not None:
        config.setdefault("options", {})["explicit_enablement"] = env_options_explicit.lower() in ("true", "1", "yes")
    env_options_approved = os.environ.get("OPTIONS_ACCOUNT_APPROVED")
    if env_options_approved is not None:
        config.setdefault("options", {})["account_approved"] = env_options_approved.lower() in ("true", "1", "yes")
    env_options_status = os.environ.get("OPTIONS_APPROVAL_STATUS")
    if env_options_status:
        config.setdefault("options", {})["approval_status"] = env_options_status.lower()
    env_crypto_live = os.environ.get("CRYPTO_LIVE_ENABLED")
    if env_crypto_live is not None:
        config.setdefault("crypto", {})["live_enabled"] = env_crypto_live.lower() in ("true", "1", "yes")

    config = _normalize_alpaca_only_config(config)
    _cached_config = config
    return config


def get_config() -> dict:
    """Return cached config or load from disk."""
    if _cached_config is None:
        return load_config()
    return _cached_config


def _deep_merge(base: dict, override: dict) -> dict:
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_repo_env() -> None:
    """Load simple KEY=VALUE pairs from the repo-local .env without overriding shell env."""
    repo_root = _CONFIG_DIR.parents[1]
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _normalize_alpaca_only_config(config: dict) -> dict:
    """Force this branch's active runtime config to the Alpaca-only contract."""
    obsolete = [
        "supported_asset_classes",
        "future_asset_classes",
    ]
    for key in obsolete:
        config.pop(key, None)

    config["active_broker"] = "alpaca"
    config["active_data_provider"] = "alpaca"
    config.setdefault("trading_mode", "simulation")
    if config["trading_mode"] not in {"simulation", "paper", "live"}:
        config["trading_mode"] = "simulation"
    config.setdefault("default_asset_class", "stocks")
    config["active_asset_classes"] = ["stocks", "options", "crypto"]
    config["default_data_source"] = "alpaca"

    paper_trading = config.setdefault("paper_trading", {})
    paper_trading.setdefault("assigned_capital", None)
    paper_trading.setdefault("use_assigned_capital_limit", False)

    alpaca = config.setdefault("alpaca", {})
    alpaca.update({
        "enabled": True,
        "require_env_credentials": True,
        "api_key_env_var": "ALPACA_API_KEY",
        "api_secret_env_var": "ALPACA_API_SECRET",
        "oauth_token_env_var": "ALPACA_OAUTH_TOKEN",
        "is_paper_env_var": "ALPACA_IS_PAPER",
    })
    alpaca.setdefault("paper", True)
    alpaca.setdefault("data_enabled", True)
    alpaca.setdefault("execution_enabled", True)
    alpaca.setdefault("data_feed", "iex")
    alpaca.setdefault("extended_hours_data_feed", "sip")
    alpaca.setdefault("market", "us")
    alpaca.setdefault("mock_paper_submission", False)
    alpaca.setdefault("allow_extended_hours", False)
    alpaca.setdefault("marketable_limit_offset_pct", 0.2)

    scheduler = config.setdefault("scheduler", {})
    scheduler.setdefault("enabled", False)
    scheduler.setdefault("interval_seconds", 60)
    scheduler.setdefault("reconcile_interval_seconds", 30)
    scheduler.setdefault("catch_up_on_start", True)

    config.setdefault("stocks", {"enabled": True, "live_enabled": False, "paper_enabled": True})
    config["stocks"].update({
        "enabled": bool(config["stocks"].get("enabled", True)),
        "live_enabled": bool(config["stocks"].get("live_enabled", False)),
        "paper_enabled": bool(config["stocks"].get("paper_enabled", True)),
        "sizing_mode": config["stocks"].get("sizing_mode", "notional"),
        "min_order_notional": float(config["stocks"].get("min_order_notional", 1.00)),
        "max_order_notional": (
            float(config["stocks"]["max_order_notional"])
            if config["stocks"].get("max_order_notional") is not None
            else None
        ),
    })
    if config["stocks"]["sizing_mode"] != "notional":
        config["stocks"]["sizing_mode"] = "notional"

    options = config.setdefault("options", {})
    options.setdefault("enabled", True)
    options.setdefault("live_enabled", False)
    options.setdefault("paper_enabled", True)
    options.setdefault("require_explicit_enablement", True)
    options.setdefault("explicit_enablement", True)
    options.setdefault("approval_status", "pending")
    options.setdefault("account_approved", False)
    options.setdefault("max_contracts_per_trade", 1)
    options.setdefault("allow_multileg_orders", False)

    crypto = config.setdefault("crypto", {})
    crypto.setdefault("enabled", True)
    crypto.setdefault("live_enabled", False)
    crypto.setdefault("paper_enabled", False)
    crypto.setdefault("require_explicit_enablement", True)
    crypto.setdefault("explicit_enablement", False)
    crypto.setdefault("max_notional_per_trade", 100)
    crypto.setdefault("allowed_symbols", ["BTC/USD", "ETH/USD"])

    orb = config.setdefault("stocks_in_play_orb_v1", {})
    orb["allowed_asset_class"] = "stocks"
    orb["data_source"] = "alpaca"
    orb.setdefault("premarket_session_start", "04:00")
    orb.setdefault("rth_end", "16:00")
    orb.setdefault("postmarket_session_end", "20:00")
    orb.setdefault("extended_hours_signals", "rth_only")
    return config
