"""Broker reconciliation for Alpaca orders and positions."""

from __future__ import annotations

from dataclasses import dataclass

from backend.database import (
    get_orders_by_statuses,
    insert_reconciliation_run,
    save_positions,
    update_order,
)
from backend.services.broker_factory import get_broker_service


OPEN_ORDER_STATUSES = [
    "pending_broker_submission",
    "accepted",
    "paper_submitted",
    "live_submitted",
    "partially_filled",
]


def _as_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ReconciliationService:
    cfg: dict

    def sync_positions(self) -> dict:
        broker = get_broker_service(self.cfg)
        response = broker.positions()
        if response.get("status") != "ok":
            run = insert_reconciliation_run(
                run_type="positions",
                status=response.get("status", "error"),
                summary={"saved": 0, "source": "alpaca"},
                mismatches=[{"type": "positions_unavailable", "detail": response.get("error") or response.get("status")}],
            )
            return {"status": response.get("status"), "positions": [], "run": run}

        positions = [self._normalize_position(p) for p in response.get("positions", [])]
        save_positions(positions, source="alpaca")
        run = insert_reconciliation_run(
            run_type="positions",
            status="ok",
            summary={"saved": len(positions), "source": "alpaca"},
            mismatches=[],
        )
        return {"status": "ok", "positions": positions, "run": run}

    def reconcile_orders(self) -> dict:
        broker = get_broker_service(self.cfg)
        response = broker.orders()
        if response.get("status") != "ok":
            run = insert_reconciliation_run(
                run_type="orders",
                status=response.get("status", "error"),
                summary={"local_open": 0, "broker_open": 0, "updated": 0},
                mismatches=[{"type": "orders_unavailable", "detail": response.get("error") or response.get("status")}],
            )
            return {"status": response.get("status"), "updated": [], "mismatches": run["mismatches"], "run": run}

        broker_orders = [self._normalize_broker_order(o) for o in response.get("orders", [])]
        by_client = {o["client_order_id"]: o for o in broker_orders if o.get("client_order_id")}
        by_broker = {o["broker_order_id"]: o for o in broker_orders if o.get("broker_order_id")}

        local_orders = get_orders_by_statuses(OPEN_ORDER_STATUSES, limit=500)
        updated: list[dict] = []
        mismatches: list[dict] = []
        matched_broker_ids: set[str] = set()

        paper = self.cfg.get("trading_mode") != "live"
        for order in local_orders:
            broker_order = None
            if order.get("client_order_id"):
                broker_order = by_client.get(order["client_order_id"])
            if broker_order is None and order.get("broker_order_id"):
                broker_order = by_broker.get(order["broker_order_id"])

            if broker_order is None:
                if order.get("broker_order_id") or order.get("client_order_id"):
                    mismatches.append({"type": "local_missing_at_broker", "order_id": order["id"], "symbol": order["symbol"]})
                continue

            matched_broker_ids.add(str(broker_order.get("broker_order_id") or broker_order.get("client_order_id")))
            mapped_status = broker.map_order_status(str(broker_order.get("status") or ""), paper=paper)
            fields = {
                "broker_order_id": broker_order.get("broker_order_id") or order.get("broker_order_id"),
                "client_order_id": broker_order.get("client_order_id") or order.get("client_order_id"),
                "execution_status": mapped_status,
            }
            if mapped_status != order.get("execution_status") or fields["broker_order_id"] != order.get("broker_order_id"):
                updated.append(update_order(order["id"], **fields))
            if mapped_status != order.get("execution_status"):
                mismatches.append({
                    "type": "status_changed",
                    "order_id": order["id"],
                    "local_status": order.get("execution_status"),
                    "broker_status": broker_order.get("status"),
                    "mapped_status": mapped_status,
                })

        local_client_ids = {o.get("client_order_id") for o in local_orders if o.get("client_order_id")}
        local_broker_ids = {o.get("broker_order_id") for o in local_orders if o.get("broker_order_id")}
        for broker_order in broker_orders:
            key = str(broker_order.get("broker_order_id") or broker_order.get("client_order_id"))
            if key in matched_broker_ids:
                continue
            if broker_order.get("client_order_id") not in local_client_ids and broker_order.get("broker_order_id") not in local_broker_ids:
                mismatches.append({
                    "type": "broker_order_missing_locally",
                    "broker_order_id": broker_order.get("broker_order_id"),
                    "client_order_id": broker_order.get("client_order_id"),
                    "symbol": broker_order.get("symbol"),
                    "status": broker_order.get("status"),
                })

        run_status = "mismatch" if mismatches else "ok"
        run = insert_reconciliation_run(
            run_type="orders",
            status=run_status,
            summary={"local_open": len(local_orders), "broker_open": len(broker_orders), "updated": len(updated)},
            mismatches=mismatches,
        )
        return {"status": run_status, "updated": updated, "mismatches": mismatches, "run": run}

    @staticmethod
    def _normalize_position(position: dict) -> dict:
        return {
            "symbol": str(position.get("symbol", "")).upper(),
            "quantity": _as_float(position.get("qty") if position.get("qty") is not None else position.get("quantity")) or 0,
            "avg_cost": _as_float(position.get("avg_entry_price") if position.get("avg_entry_price") is not None else position.get("avg_cost")),
            "market_value": _as_float(position.get("market_value")),
            "unrealised_pnl": _as_float(position.get("unrealized_pl") if position.get("unrealized_pl") is not None else position.get("unrealised_pnl")),
            "account": position.get("account_number") or position.get("account"),
        }

    @staticmethod
    def _normalize_broker_order(order: dict) -> dict:
        return {
            "broker_order_id": order.get("id") or order.get("broker_order_id"),
            "client_order_id": order.get("client_order_id"),
            "symbol": str(order.get("symbol", "")).upper(),
            "side": order.get("side"),
            "status": order.get("status"),
            "quantity": _as_float(order.get("qty") if order.get("qty") is not None else order.get("quantity")),
            "notional": _as_float(order.get("notional")),
        }
