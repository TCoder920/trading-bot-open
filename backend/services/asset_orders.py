"""Options & crypto order submission (strategy-facing).

This is the non-stock analogue of :mod:`backend.services.order_execution` (which drives the
stock ORB autonomous loop). Asset-class trading strategies call :meth:`AssetOrderService.place_order`
to submit an individual option or crypto order with an optional take-profit / stop-loss, with risk
approval, idempotency, and persistence. Take-profit / stop-loss are stored as managed-exit metadata
and fired by :mod:`backend.services.position_manager` (broker-agnostic, works for crypto too where
native bracket orders are unsupported).

This is NOT a manual-trading surface: there is no UI ticket and no order-placement HTTP endpoint.
All bot trading is strategy-driven; any manual trading is done outside the bot (Alpaca directly).

Safety: simulation stays mocked; real submission only in paper/live with credentials and the
asset-class gates satisfied. The protective kill switch blocks new entries (buys) but never exits.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass

from backend.database import (
    get_order_by_client_order_id,
    insert_broker_order_event,
    insert_log,
    insert_order,
    update_order,
)
from backend.services.broker_factory import get_broker_service
from lumibot.custom_config.risk_engine import RiskEngine

_SUBMIT_LOCK = threading.RLock()

_SUPPORTED = {"options", "crypto"}


@dataclass
class AssetOrderResult:
    status: str
    reason: str = ""
    order_id: int | None = None
    client_order_id: str | None = None
    idempotent: bool = False
    broker_result: dict | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "idempotent": self.idempotent,
            "broker_result": self.broker_result,
        }


class AssetOrderService:
    def __init__(self, cfg: dict, *, broker=None, risk: RiskEngine | None = None):
        self.cfg = cfg
        self.broker = broker or get_broker_service(cfg)
        self.risk = risk or RiskEngine(cfg)

    def place_order(
        self,
        *,
        asset_class: str,
        symbol: str,
        side: str,
        quantity: float | None = None,
        notional: float | None = None,
        order_type: str = "market",
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str | None = None,
        option_symbol: str | None = None,
        underlying_symbol: str | None = None,
        option_type: str | None = None,
        strike: float | None = None,
        expiration: str | None = None,
        premium: float | None = None,
        legs: list[dict] | None = None,
        take_profit: float | None = None,
        stop_loss: float | None = None,
        role: str = "entry",
        strategy_id: str = "unassigned",
        client_order_id: str | None = None,
    ) -> AssetOrderResult:
        ac = (asset_class or "").lower()
        if ac not in _SUPPORTED:
            return AssetOrderResult("failed", f"AssetOrderService handles {sorted(_SUPPORTED)}, not '{ac}'")

        side_l = (side or "").lower()
        if side_l not in {"buy", "sell"}:
            return AssetOrderResult("failed", "side must be buy or sell")
        is_exit = side_l == "sell"

        # Protective kill switch: blocks new exposure (buys), never exits.
        if not is_exit and not self.risk.allows_new_entries:
            return AssetOrderResult("blocked", f"kill switch active: {', '.join(self.risk.kill_switch_reasons)}")

        # Risk sizing (dollars) per asset class.
        risk_amount = self._risk_amount(ac, quantity, notional, premium, limit_price)

        coid = client_order_id or f"tb2-{strategy_id}-{ac}-{(option_symbol or symbol).upper()}-{role}-{uuid.uuid4().hex[:8]}"

        with _SUBMIT_LOCK:
            existing = get_order_by_client_order_id(coid)
            if existing is not None:
                return AssetOrderResult("duplicate", "idempotent: order already exists for this client_order_id",
                                        order_id=existing["id"], client_order_id=coid, idempotent=True)
            stored_symbol = (option_symbol or symbol).upper()
            metadata = {"role": role, "asset_class": ac}
            if take_profit is not None:
                metadata["take_profit"] = float(take_profit)
            if stop_loss is not None:
                metadata["stop_loss"] = float(stop_loss)
            if legs:
                metadata["legs"] = legs
            order = insert_order(
                symbol=stored_symbol,
                side=side_l,
                quantity=quantity,
                dollar_amount=risk_amount,
                order_type=order_type,
                time_in_force=time_in_force or ("day" if ac == "options" else "gtc"),
                strategy=strategy_id,
                strategy_id=strategy_id,
                asset_class=ac,
                broker="alpaca",
                paper=self.cfg.get("trading_mode") != "live",
                client_order_id=coid,
                sizing_mode="contracts" if ac == "options" else ("notional" if notional is not None else "crypto"),
                notional=notional,
                limit_price=limit_price,
                stop_price=stop_price,
                underlying_symbol=underlying_symbol,
                option_type=option_type,
                strike=strike,
                expiration=expiration,
                premium=premium,
                quote_currency="USD" if ac == "crypto" else None,
                metadata=metadata,
            )

        # Risk approval: buys via entry gate, sells via exit (risk-reducing) path.
        if is_exit:
            approved, reason = self.risk.approve_exit(stored_symbol, risk_amount, ac)
        else:
            approved, reason = self.risk.approve_proposal(stored_symbol, risk_amount, ac)
        if not approved:
            update_order(order["id"], risk_approved=0, risk_status="rejected", risk_reason=reason,
                         execution_status="risk_rejected")
            return AssetOrderResult("risk_rejected", reason, order_id=order["id"], client_order_id=coid)

        update_order(order["id"], risk_approved=1, risk_status="approved", risk_reason=reason,
                     review_status="reviewed", execution_status="pending_broker_submission")

        broker_order = {
            "id": order["id"],
            "symbol": stored_symbol,
            "option_symbol": option_symbol,
            "side": side_l,
            "asset_class": ac,
            "quantity": quantity,
            "notional": notional,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "underlying_symbol": underlying_symbol,
            "option_type": option_type,
            "strike": strike,
            "expiration": expiration,
            "premium": premium,
            "legs": legs,
            "client_order_id": coid,
            "sizing_mode": "notional" if (ac == "crypto" and notional is not None) else None,
        }
        result = self.broker.submit_order(broker_order)
        status = result.get("execution_status", "failed")
        details = result.get("details") or result
        fields: dict = {
            "broker": "alpaca",
            "paper": int(bool(result.get("paper", self.cfg.get("trading_mode") != "live"))),
            "execution_status": status,
            "execution_details_json": json.dumps(details),
        }
        if result.get("broker_order_id"):
            fields["broker_order_id"] = result["broker_order_id"]
        if result.get("client_order_id"):
            fields["client_order_id"] = result["client_order_id"]
        if result.get("errors"):
            fields["error"] = "; ".join(result["errors"])
        update_order(order["id"], **fields)
        insert_broker_order_event(
            order_id=order["id"], event_type="submit", status=status,
            broker_order_id=result.get("broker_order_id"),
            client_order_id=result.get("client_order_id") or coid,
            payload=details.get("payload") if isinstance(details, dict) else None,
            response=result, error=fields.get("error"),
        )
        insert_log("order", f"{ac} order {stored_symbol} {role}: {status}",
                   symbol=stored_symbol, strategy=strategy_id,
                   details={"take_profit": take_profit, "stop_loss": stop_loss})
        return AssetOrderResult(status, reason, order_id=order["id"], client_order_id=coid, broker_result=result)

    @staticmethod
    def _risk_amount(asset_class: str, quantity, notional, premium, limit_price) -> float:
        if asset_class == "options":
            per = float(premium if premium is not None else (limit_price or 0))
            return round(per * 100 * float(quantity or 0), 2)
        # crypto
        if notional is not None:
            return float(notional)
        if quantity is not None and limit_price is not None:
            return round(float(quantity) * float(limit_price), 2)
        return 0.0
