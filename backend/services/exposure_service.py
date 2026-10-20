"""Capital and exposure checks for order validation."""

from __future__ import annotations

from dataclasses import dataclass

from backend.database import get_open_order_exposure, get_position_exposure, get_positions
from backend.services.broker_factory import get_broker_service


def _as_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ExposureService:
    cfg: dict

    def snapshot(self) -> dict:
        paper_trading = self.cfg.get("paper_trading", {})
        assigned_requested = bool(paper_trading.get("use_assigned_capital_limit", False))
        assigned_capital = _as_float(paper_trading.get("assigned_capital"))
        assigned_enabled = assigned_requested and assigned_capital is not None and assigned_capital > 0

        account = get_broker_service(self.cfg).account()
        account_data = account.get("account") if account.get("status") == "ok" else {}
        buying_power = _as_float((account_data or {}).get("buying_power"))
        equity = _as_float((account_data or {}).get("equity"))

        capital_limit = None
        capital_source = "unlimited_local"
        if assigned_enabled:
            capital_limit = assigned_capital
            capital_source = "assigned_capital"
        elif buying_power is not None:
            capital_limit = buying_power
            capital_source = "alpaca_buying_power"
        elif equity is not None:
            capital_limit = equity
            capital_source = "alpaca_equity"

        position_source = self._position_source()
        position_exposure = get_position_exposure(position_source) if position_source else 0.0
        open_order_exposure = get_open_order_exposure()
        total_exposure = position_exposure + open_order_exposure
        remaining_capital = None
        if capital_limit is not None:
            remaining_capital = max(0.0, capital_limit - total_exposure)

        return {
            "assigned_capital_enabled": assigned_enabled,
            "assigned_capital_requested": assigned_requested,
            "assigned_capital": assigned_capital,
            "account_configured": bool(account.get("configured")),
            "account_status": account.get("status"),
            "account_buying_power": buying_power,
            "account_equity": equity,
            "capital_limit": capital_limit,
            "capital_source": capital_source,
            "position_source": position_source,
            "position_exposure": position_exposure,
            "open_order_exposure": open_order_exposure,
            "total_exposure": total_exposure,
            "remaining_capital": remaining_capital,
        }

    def approve_order_amount(self, amount: float, *, side: str = "buy") -> tuple[bool, str, dict]:
        snapshot = self.snapshot()
        if side.lower() != "buy":
            return True, "sell order does not consume buying capital", snapshot

        capital_limit = snapshot.get("capital_limit")
        if capital_limit is None:
            return True, "capital check skipped because broker account capital is unavailable in local mode", snapshot

        projected = snapshot["total_exposure"] + float(amount)
        if projected > capital_limit:
            return False, (
                f"projected exposure {projected:.2f} exceeds {snapshot['capital_source']} {capital_limit:.2f}"
            ), snapshot
        return True, "capital exposure approved", snapshot

    @staticmethod
    def _position_source() -> str | None:
        alpaca_positions = get_positions(source="alpaca")
        if alpaca_positions:
            return "alpaca"
        local_positions = get_positions(source="local")
        if local_positions:
            return "local"
        return None
