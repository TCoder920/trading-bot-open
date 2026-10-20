"""Managed take-profit / stop-loss exits for options & crypto positions.

Native bracket orders are not supported for crypto and are awkward across asset classes, so
TP/SL is managed here: we watch real quotes and submit a closing order when a level is crossed.

NO-FABRICATION RULE: if there is no real quote this tick, we do nothing (we never act on an
invented price). Long-only management: a filled BUY entry with take_profit/stop_loss metadata is
closed with a SELL when price crosses a level.

Idempotency: each managed exit uses a deterministic client_order_id derived from the entry, so a
restart or a repeated tick cannot double-submit the same exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.database import get_order_by_client_order_id, get_orders, insert_log
from backend.services.asset_orders import AssetOrderService
from backend.services.crypto_service import CryptoService
from backend.services.options_service import OptionsService

FILLED_STATUSES = ("paper_filled", "live_filled")
MANAGED_ASSET_CLASSES = {"options", "crypto"}


@dataclass
class ManageResult:
    checked: int = 0
    exits: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"checked": self.checked, "exits": self.exits, "warnings": self.warnings}


@dataclass
class PositionManager:
    cfg: dict
    asset_orders: AssetOrderService | None = None
    options: OptionsService | None = None
    crypto: CryptoService | None = None

    def __post_init__(self):
        if self.asset_orders is None:
            self.asset_orders = AssetOrderService(self.cfg)
        if self.options is None:
            self.options = OptionsService(self.cfg)
        if self.crypto is None:
            self.crypto = CryptoService(self.cfg)

    def _open_managed_entries(self) -> list[dict]:
        seen: dict[int, dict] = {}
        for status in FILLED_STATUSES:
            for o in get_orders(status=status, limit=500):
                if o.get("asset_class") not in MANAGED_ASSET_CLASSES:
                    continue
                if (o.get("side") or "").lower() != "buy":
                    continue
                meta = o.get("metadata") or {}
                if meta.get("take_profit") is None and meta.get("stop_loss") is None:
                    continue
                seen[o["id"]] = o
        return list(seen.values())

    def _current_price(self, order: dict, result: ManageResult) -> float | None:
        ac = order.get("asset_class")
        symbol = order["symbol"]
        if ac == "options":
            q = self.options.latest_quote(symbol)
        else:
            q = self.crypto.latest_quote(symbol)
        if q.get("warning"):
            result.warnings.append(f"{symbol}: {q['warning']}")
        # Sell side fills near the bid; fall back to mid only if bid is absent.
        price = q.get("bid") or q.get("mid")
        return float(price) if price is not None else None

    def manage(self) -> ManageResult:
        result = ManageResult()
        for entry in self._open_managed_entries():
            result.checked += 1
            meta = entry.get("metadata") or {}
            tp = meta.get("take_profit")
            sl = meta.get("stop_loss")
            entry_coid = entry.get("client_order_id") or f"order-{entry['id']}"
            exit_coid = f"{entry_coid}-mexit"
            if get_order_by_client_order_id(exit_coid) is not None:
                continue  # exit already submitted for this position
            price = self._current_price(entry, result)
            if price is None:
                continue  # honest: no real quote, do not act
            reason = None
            if tp is not None and price >= float(tp):
                reason = "target"
            elif sl is not None and price <= float(sl):
                reason = "stop"
            if reason is None:
                continue
            ac = entry["asset_class"]
            order_type = "limit" if ac == "options" else "market"
            res = self.asset_orders.place_order(
                asset_class=ac,
                symbol=entry["symbol"],
                option_symbol=entry["symbol"] if ac == "options" else None,
                side="sell",
                quantity=entry.get("quantity"),
                order_type=order_type,
                limit_price=price if order_type == "limit" else None,
                role=f"exit-{reason}",
                strategy_id=entry.get("strategy_id") or "unassigned",
                client_order_id=exit_coid,
                underlying_symbol=entry.get("underlying_symbol"),
                option_type=entry.get("option_type"),
                strike=entry.get("strike"),
                expiration=entry.get("expiration"),
            )
            result.exits.append({**res.to_dict(), "symbol": entry["symbol"],
                                 "reason": reason, "price": price})
            insert_log("order", f"Managed {reason} exit submitted: {entry['symbol']} @ {price}",
                       symbol=entry["symbol"], details={"entry_order_id": entry["id"], "reason": reason})
        return result
