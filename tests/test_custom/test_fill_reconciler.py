"""Tests for order-lifecycle / fill reconciliation -> PnL -> kill switch (#4, #6, #7)."""

import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import backend.database as db

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def temp_db():
    prev = db.DB_PATH
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db.DB_PATH = type(prev)(tmp.name)
    db.init_db()
    yield
    db.DB_PATH = prev


from backend.services.fill_reconciler import FillReconciler  # noqa: E402
from lumibot.custom_config.risk_engine import RiskEngine  # noqa: E402
from lumibot.custom_strategies.session import SessionClock  # noqa: E402


def _cfg(max_daily_loss=50):
    return {
        "active_broker": "alpaca", "active_data_provider": "alpaca", "default_asset_class": "stocks",
        "trading_mode": "paper", "live_trading_enabled": False, "active_asset_classes": ["stocks"],
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "stocks": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                   "sizing_mode": "notional", "max_order_notional": 1000000},
        "watchlist": {"stocks": ["AAPL"]},
        "risk_limits": {"max_dollars_per_trade": 1000000, "max_loss_per_trade": 1000,
                        "max_daily_loss": max_daily_loss, "max_trades_per_day": 1000,
                        "max_open_positions": 1000},
        "stocks_in_play_orb_v1": {},
    }


class FakeBroker:
    def __init__(self, orders):
        self._orders = orders

    def orders(self):
        return {"status": "ok", "orders": self._orders}

    def map_order_status(self, status, paper=True):
        s = (status or "").lower()
        if s == "filled":
            return "paper_filled" if paper else "live_filled"
        if s == "partially_filled":
            return "partially_filled"
        if s in {"new", "accepted"}:
            return "accepted"
        if s in {"canceled", "expired"}:
            return "canceled"
        if s == "rejected":
            return "rejected"
        return "failed"


def _seed_entry_buy(symbol="AAPL", price=100.0, qty=10):
    order = db.insert_order(symbol=symbol, side="buy", quantity=qty, dollar_amount=price * qty,
                            order_type="limit", limit_price=price, client_order_id="coid-buy",
                            strategy_id="stocks_in_play_orb_v1")
    db.update_order(order["id"], execution_status="paper_filled")
    return order


def _seed_open_sell(symbol="AAPL", qty=10):
    order = db.insert_order(symbol=symbol, side="sell", quantity=qty, dollar_amount=0,
                            order_type="market", client_order_id="coid-sell",
                            strategy_id="stocks_in_play_orb_v1")
    db.update_order(order["id"], execution_status="paper_submitted")
    return order


class TestFillReconciliation:
    def test_sell_fill_records_loss_and_engages_kill_switch(self):
        _seed_entry_buy(price=100.0, qty=10)
        sell = _seed_open_sell(qty=10)
        broker = FakeBroker([
            {"id": "bo-sell", "client_order_id": "coid-sell", "symbol": "AAPL", "side": "sell",
             "status": "filled", "filled_avg_price": 95.0, "filled_qty": 10},
        ])
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        risk = RiskEngine(_cfg(max_daily_loss=50), clock=clock)
        rec = FillReconciler(_cfg(max_daily_loss=50), broker=broker, risk=risk)
        result = rec.reconcile()

        assert result["status"] == "ok"
        assert len(result["fills"]) == 1
        assert result["fills"][0]["pnl"] == pytest.approx(-50.0)
        assert result["kill_switch_active"] is True
        # Order transitioned to filled and persisted.
        assert db.get_order(sell["id"])["execution_status"] == "paper_filled"
        # Ledger persisted (single source of truth).
        ledger = db.get_daily_ledger(clock.session_day_str())
        assert ledger["realised_loss"] == pytest.approx(50.0)

    def test_fill_recorded_once(self):
        _seed_entry_buy(price=100.0, qty=10)
        _seed_open_sell(qty=10)
        broker = FakeBroker([
            {"id": "bo-sell", "client_order_id": "coid-sell", "symbol": "AAPL", "side": "sell",
             "status": "filled", "filled_avg_price": 99.0, "filled_qty": 10},
        ])
        rec = FillReconciler(_cfg())
        rec.broker = broker
        rec.reconcile()
        # Second reconcile must not double-count the trade.
        result2 = rec.reconcile()
        assert result2["fills"] == []
        assert len(db.get_trades(limit=50)) == 1

    def test_profit_does_not_engage_kill_switch(self):
        _seed_entry_buy(price=100.0, qty=10)
        _seed_open_sell(qty=10)
        broker = FakeBroker([
            {"id": "bo-sell", "client_order_id": "coid-sell", "symbol": "AAPL", "side": "sell",
             "status": "filled", "filled_avg_price": 110.0, "filled_qty": 10},
        ])
        rec = FillReconciler(_cfg(max_daily_loss=50), broker=broker)
        result = rec.reconcile()
        assert result["fills"][0]["pnl"] == pytest.approx(100.0)
        assert result["kill_switch_active"] is False

    def test_broker_unavailable(self):
        class DownBroker:
            def orders(self):
                return {"status": "error", "error": "boom"}
            def map_order_status(self, s, paper=True):
                return "failed"
        rec = FillReconciler(_cfg(), broker=DownBroker())
        result = rec.reconcile()
        assert result["status"] == "error"
