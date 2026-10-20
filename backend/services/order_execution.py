"""Idempotent, session-aware order execution for the autonomous loop.

Responsibilities:

* Pick the correct Alpaca order type for the current session (RTH vs extended hours)
  via :mod:`lumibot.custom_strategies.order_types`.
* Guarantee idempotency: a given (strategy, symbol, role, session-day) intent maps to one
  deterministic ``client_order_id``; duplicate submissions (concurrent requests, restarts,
  re-ticks) are detected and skipped before anything reaches the broker.
* Enforce the kill switch and risk approval before submitting.
* Persist the order, broker events, and transition the execution status.

Simulation stays fully mocked (delegated to ``AlpacaService.submit_order``). Live stays
disabled by default. Real submission only occurs in paper/live with credentials present.
"""

from __future__ import annotations

import json
import threading
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
from lumibot.custom_strategies.order_types import resolve_order_type
from lumibot.custom_strategies.session import EXTENDED_SESSIONS, Session, SessionClock, SessionWindows

# Serializes the check-and-insert so concurrent FastAPI workers/threads cannot create
# two orders for the same idempotency key in the race window before the DB row exists.
_SUBMIT_LOCK = threading.RLock()


@dataclass
class ExecutionResult:
    status: str
    reason: str = ""
    order_id: int | None = None
    client_order_id: str | None = None
    idempotent: bool = False
    order_spec: dict | None = None
    broker_result: dict | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "idempotent": self.idempotent,
            "order_spec": self.order_spec,
            "broker_result": self.broker_result,
        }


class OrderExecutionService:
    def __init__(self, cfg: dict, *, broker=None, risk: RiskEngine | None = None,
                 clock: SessionClock | None = None):
        self.cfg = cfg
        self._orb_cfg = cfg.get("stocks_in_play_orb_v1", {})
        self.clock = clock or SessionClock(SessionWindows.from_config(self._orb_cfg))
        self.broker = broker or get_broker_service(cfg)
        self.risk = risk or RiskEngine(cfg, clock=self.clock)

    def build_client_order_id(self, strategy_id: str, symbol: str, role: str,
                              session_day: str, seq: int = 0) -> str:
        return f"tb2-{strategy_id}-{symbol.upper()}-{role}-{session_day}-{seq}"

    def submit_intent(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        intent: str,
        reference_price: float | None,
        role: str,
        strategy_id: str = "stocks_in_play_orb_v1",
        asset_class: str = "stocks",
        stop_price: float | None = None,
        limit_price: float | None = None,
        seq: int = 0,
    ) -> ExecutionResult:
        session = self.clock.session()
        session_day = self.clock.session_day_str()

        if session == Session.CLOSED:
            return ExecutionResult("skipped", "market closed (no tradeable session)")

        extended = session in EXTENDED_SESSIONS
        if extended and not self.cfg.get("alpaca", {}).get("allow_extended_hours", False):
            return ExecutionResult("skipped", "extended hours trading is disabled")

        is_exit = side.lower() == "sell"
        # Protective kill switch: halts NEW exposure (entries/buys) immediately, but
        # risk-reducing exits (sells / flatten) are still allowed so the bot can get flat.
        if not is_exit and not self.risk.allows_new_entries:
            return ExecutionResult("blocked", f"kill switch active: {', '.join(self.risk.kill_switch_reasons)}")

        if quantity is None or float(quantity) <= 0:
            return ExecutionResult("skipped", "non-positive quantity")

        try:
            spec = resolve_order_type(
                side=side,
                session=session,
                intent=intent,
                reference_price=reference_price,
                stop_price=stop_price,
                limit_price=limit_price,
                config={
                    "marketable_limit_offset_pct": self.cfg.get("alpaca", {}).get("marketable_limit_offset_pct", 0.2),
                    "tick_size": self._orb_cfg.get("tick_size", 0.01),
                },
            )
        except ValueError as exc:
            return ExecutionResult("failed", f"order-type resolution failed: {exc}")

        coid = self.build_client_order_id(strategy_id, symbol, role, session_day, seq)

        with _SUBMIT_LOCK:
            existing = get_order_by_client_order_id(coid)
            if existing is not None:
                return ExecutionResult(
                    "duplicate",
                    "idempotent: order already exists for this intent",
                    order_id=existing["id"],
                    client_order_id=coid,
                    idempotent=True,
                    order_spec=spec.to_payload_fields(),
                )

            order = insert_order(
                symbol=symbol,
                side=side,
                quantity=int(quantity) if float(quantity).is_integer() else quantity,
                dollar_amount=round(float(quantity) * float(reference_price or spec.limit_price or 0), 2),
                order_type=spec.order_type,
                time_in_force=spec.time_in_force,
                strategy=strategy_id,
                strategy_id=strategy_id,
                asset_class=asset_class,
                broker="alpaca",
                paper=self.cfg.get("trading_mode") != "live",
                client_order_id=coid,
                sizing_mode="whole_share",
                limit_price=spec.limit_price,
                stop_price=spec.stop_price,
                metadata={
                    "role": role,
                    "intent": intent,
                    "session": session,
                    "extended_hours": spec.extended_hours,
                    "converted_from": spec.converted_from,
                    "spec_notes": spec.notes,
                },
            )

        # Risk approval applies to NEW exposure (buys) via approve_proposal. Risk-reducing
        # exits (sells) go through approve_exit, which is not gated by entry limits, the
        # daily-loss limit, or the kill switch — exits reduce risk and must always be allowed.
        dollar_amt = order["dollar_amount"] or 0.0
        if is_exit:
            approved, reason = self.risk.approve_exit(symbol.upper(), dollar_amt, asset_class)
        else:
            approved, reason = self.risk.approve_proposal(symbol.upper(), dollar_amt, asset_class)
        if not approved:
            update_order(order["id"], risk_approved=0, risk_status="rejected", risk_reason=reason,
                         execution_status="risk_rejected")
            insert_log("order", f"Autonomous order risk-rejected: {symbol} {role}",
                       symbol=symbol, strategy=strategy_id, level="warning",
                       details={"reason": reason})
            return ExecutionResult("risk_rejected", reason, order_id=order["id"], client_order_id=coid,
                                   order_spec=spec.to_payload_fields())

        update_order(order["id"], risk_approved=1, risk_status="approved", risk_reason=reason,
                     review_status="reviewed", execution_status="pending_broker_submission")

        # Build the broker order dict (extended_hours plumbed through prepare_order_payload).
        broker_order = {
            "id": order["id"],
            "symbol": symbol.upper(),
            "side": side,
            "asset_class": asset_class,
            "quantity": order["quantity"],
            "order_type": spec.order_type,
            "time_in_force": spec.time_in_force,
            "extended_hours": spec.extended_hours,
            "limit_price": spec.limit_price,
            "stop_price": spec.stop_price,
            "client_order_id": coid,
            "sizing_mode": "whole_share",
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
        insert_log("order", f"Autonomous order {symbol} {role}: {status}",
                   symbol=symbol, strategy=strategy_id, details={"spec": spec.to_payload_fields()})
        return ExecutionResult(status, reason, order_id=order["id"], client_order_id=coid,
                               order_spec=spec.to_payload_fields(), broker_result=result)
