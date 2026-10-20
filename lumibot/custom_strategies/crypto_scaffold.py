"""Safe crypto strategy scaffolding.

No autonomous crypto strategy is enabled in this pass. This module centralizes
readiness metadata used by API/UI status surfaces.
"""

STRATEGY_ID = "crypto_scaffold"


def readiness(config: dict) -> dict:
    crypto = config.get("crypto", {})
    return {
        "strategy_id": STRATEGY_ID,
        "asset_class": "crypto",
        "enabled": bool(crypto.get("enabled", True)),
        "paper_enabled": bool(crypto.get("paper_enabled", False)),
        "live_enabled": bool(crypto.get("live_enabled", False)),
        "explicit_enablement": bool(crypto.get("explicit_enablement", False)),
        "allowed_symbols": crypto.get("allowed_symbols", []),
        "autonomous_strategy_enabled": False,
        "market_hours": "24/7",
    }
