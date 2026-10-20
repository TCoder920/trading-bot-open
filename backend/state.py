"""Shared mutable application state and config helpers."""

from __future__ import annotations

import yaml

from lumibot.custom_config.settings import _USER_OVERRIDE, load_config

_config: dict | None = None
bot_state: str = "stopped"


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> dict:
    global _config
    _config = load_config()
    return _config


def save_and_reload(cfg: dict) -> dict:
    """Persist current config to user_config.yaml and reload."""
    global _config
    _persist = {k: v for k, v in cfg.items() if k not in ("future_asset_classes",)}
    with open(_USER_OVERRIDE, "w") as f:
        yaml.dump(_persist, f, default_flow_style=False, sort_keys=False)
    _config = load_config()
    return _config
