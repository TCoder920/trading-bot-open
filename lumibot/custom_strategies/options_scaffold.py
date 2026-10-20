"""Safe options strategy scaffolding.

No autonomous options strategy is enabled in this pass. This module centralizes
readiness metadata used by API/UI status surfaces.
"""

STRATEGY_ID = "options_scaffold"


def readiness(config: dict) -> dict:
    options = config.get("options", {})
    return {
        "strategy_id": STRATEGY_ID,
        "asset_class": "options",
        "enabled": bool(options.get("enabled", True)),
        "paper_enabled": bool(options.get("paper_enabled", False)),
        "live_enabled": bool(options.get("live_enabled", False)),
        "explicit_enablement": bool(options.get("explicit_enablement", False)),
        "single_leg_ready": True,
        "multileg_ready": bool(options.get("allow_multileg_orders", False)),
        "autonomous_strategy_enabled": False,
    }

