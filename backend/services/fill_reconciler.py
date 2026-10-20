"""Order-lifecycle + fill reconciliation (polling, no websocket required).

Tracks Alpaca order state transitions (accepted → partial → filled →
canceled/rejected/expired) by polling the broker, persists fills as trades in SQLite,
realizes PnL for closing sells, and funnels realized losses into the daily ledger and
the risk-engine kill switch.

Runs on a cadence from the scheduler and once on startup so state survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.database import (
    get_daily_ledger,
    get_last_filled_buy,
    get_orders_by_statuses,
    insert_log,
    insert_reconciliation_run,
    insert_trade,
    trade_exists_for_order,
    update_daily_ledger,
    update_order,
)
from backend.services.broker_factory import get_broker_service
from lumibot.custom_config.risk_engine import RiskEngine
from lumibot.custom_strategies.session import SessionClock, SessionWindows

OPEN_ORDER_STATUSES = [
    "pending_broker_submission",
    "accepted",
    "paper_submitted",
    "live_submitted",
    "partially_filled",
]
FILLED_STATUSES = {"paper_filled", "live_filled"}


def _as_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class FillReconciler:
    cfg: dict
    broker: object | None = None
    risk: RiskEngine | None = None

    def __post_init__(self):
        if self.broker is None:
            self.broker = get_broker_service(self.cfg)
        clock = SessionClock(SessionWindows.from_config(self.cfg.get("stocks_in_play_orb_v1", {})))
        if self.risk is None:
            self.risk = RiskEngine(self.cfg, clock=clock)
        self._clock = clock
        # Hydrate the risk ledger from the persisted (SQLite) ledger — single source of truth.
        ledger = get_daily_ledger(self.risk.session_day.isoformat())
        self.risk.sync_ledger(
            trade_count=ledger.get("trade_count", 0),
            realised_loss=ledger.get("realised_loss", 0.0),
            open_positions=ledger.get("open_positions", 0),
            trade_date=self.risk.session_day.isoformat(),
        )

    def reconcile(self) -> dict:
        response = self.broker.orders()
        if response.get("status") != "ok":
            run = insert_reconciliation_run(
                run_type="fills",
                status=response.get("status", "error"),
                summary={"updated": 0, "fills": 0},
                mismatches=[{"type": "orders_unavailable", "detail": response.get("error") or response.get("status")}],
            )
            return {"status": response.get("status"), "updated": [], "fills": [], "run": run,
                    "kill_switch_active": self.risk.kill_switch_active}

        broker_orders = [self._normalize(o) for o in response.get("orders", [])]
        by_client = {o["client_order_id"]: o for o in broker_orders if o.get("client_order_id")}
        by_broker = {o["broker_order_id"]: o for o in broker_orders if o.get("broker_order_id")}

        paper = self.cfg.get("trading_mode") != "live"
        local_orders = get_orders_by_statuses(OPEN_ORDER_STATUSES, limit=500)
        updated: list[dict] = []
        fills: list[dict] = []
        realized_loss_delta = 0.0

        for order in local_orders:
            bo = None
            if order.get("client_order_id"):
                bo = by_client.get(order["client_order_id"])
            if bo is None and order.get("broker_order_id"):
                bo = by_broker.get(order["broker_order_id"])
            if bo is None:
                continue
            mapped = self.broker.map_order_status(str(bo.get("status") or ""), paper=paper)
            if mapped != order.get("execution_status"):
                updated.append(update_order(order["id"], execution_status=mapped,
                                            broker_order_id=bo.get("broker_order_id") or order.get("broker_order_id")))
            # Record the fill exactly once.
            if mapped in FILLED_STATUSES and not trade_exists_for_order(order["id"]):
                fill = self._record_fill(order, bo)
                fills.append(fill)
                realized_loss_delta += max(0.0, -(fill.get("pnl") or 0.0))

        if realized_loss_delta > 0:
            self.risk.record_fill_pnl(-realized_loss_delta)
        # Persist the ledger so SQLite stays the source of truth across restarts.
        # Keyed by the ET session day so it matches the risk engine, never the UTC date.
        snapshot = self.risk.ledger_snapshot()
        update_daily_ledger(trade_count=snapshot["trade_count"], realised_loss=snapshot["realised_loss"],
                            trade_date=self.risk.session_day.isoformat())

        if self.risk.kill_switch_active:
            insert_log("risk", "Kill switch active after fill reconciliation",
                       level="error", details={"reasons": self.risk.kill_switch_reasons,
                                                "realised_loss": snapshot["realised_loss"]})

        run = insert_reconciliation_run(
            run_type="fills",
            status="ok",
            summary={"updated": len(updated), "fills": len(fills),
                     "realised_loss": snapshot["realised_loss"],
                     "kill_switch_active": self.risk.kill_switch_active},
            mismatches=[],
        )
        return {"status": "ok", "updated": updated, "fills": fills, "run": run,
                "kill_switch_active": self.risk.kill_switch_active}

    def _record_fill(self, order: dict, broker_order: dict) -> dict:
        side = (order.get("side") or "").lower()
        fill_price = broker_order.get("filled_avg_price") or _as_float(order.get("limit_price"))
        fill_qty = broker_order.get("filled_qty") or order.get("quantity") or 0
        pnl = None
        if side == "sell" and fill_price is not None:
            entry = get_last_filled_buy(order["symbol"])
            entry_price = None
            if entry is not None:
                entry_price = _as_float((entry.get("execution_details") or {}).get("fill_price")) \
                    or _as_float(entry.get("limit_price"))
            if entry_price is not None:
                pnl = round((float(fill_price) - float(entry_price)) * float(fill_qty), 2)
        trade = insert_trade(
            order_id=order["id"],
            symbol=order["symbol"],
            side=side,
            quantity=fill_qty,
            price=fill_price,
            dollar_amount=round(float(fill_price) * float(fill_qty), 2) if fill_price is not None else None,
            strategy=order.get("strategy_id") or order.get("strategy"),
            pnl=pnl,
        )
        insert_log("order", f"Fill recorded: {side} {order['symbol']} x{fill_qty} @ {fill_price}",
                   symbol=order["symbol"], details={"order_id": order["id"], "pnl": pnl})
        return {**trade, "pnl": pnl}

    @staticmethod
    def _normalize(o: dict) -> dict:
        return {
            "broker_order_id": o.get("id") or o.get("broker_order_id"),
            "client_order_id": o.get("client_order_id"),
            "symbol": str(o.get("symbol", "")).upper(),
            "side": o.get("side"),
            "status": o.get("status"),
            "filled_avg_price": _as_float(o.get("filled_avg_price")),
            "filled_qty": _as_float(o.get("filled_qty")),
        }
