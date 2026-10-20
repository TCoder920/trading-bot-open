"""Tests for the SQLite persistence layer."""

import os
import tempfile

import pytest

# Point DB to a temp file before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()

import backend.database as db
db.DB_PATH = type(db.DB_PATH)(_tmp.name)
db.init_db()
from backend.services.exposure_service import ExposureService


class TestWatchlist:
    def test_add_and_get(self):
        db.add_watchlist_symbol("TEST1", "stocks")
        symbols = db.get_watchlist("stocks")
        assert "TEST1" in symbols

    def test_add_duplicate(self):
        db.add_watchlist_symbol("DUP1", "stocks")
        ok = db.add_watchlist_symbol("DUP1", "stocks")
        assert not ok

    def test_remove(self):
        db.add_watchlist_symbol("REM1", "stocks")
        ok = db.remove_watchlist_symbol("REM1", "stocks")
        assert ok
        assert "REM1" not in db.get_watchlist("stocks")

    def test_remove_nonexistent(self):
        ok = db.remove_watchlist_symbol("NOPE", "stocks")
        assert not ok


class TestStrategies:
    def test_create_and_get(self):
        s = db.upsert_strategy("test_strat", "ma_cross", {"fast": 10}, True)
        assert s["name"] == "test_strat"
        assert s["enabled"] is True
        assert s["config"]["fast"] == 10

    def test_update(self):
        db.upsert_strategy("upd_strat", "rsi", {"period": 14})
        db.upsert_strategy("upd_strat", "rsi", {"period": 21}, True)
        s = db.get_strategy("upd_strat")
        assert s["config"]["period"] == 21
        assert s["enabled"] is True

    def test_delete(self):
        db.upsert_strategy("del_strat", "test", {})
        ok = db.delete_strategy("del_strat")
        assert ok
        assert db.get_strategy("del_strat") is None

    def test_active_strategy(self):
        db.upsert_strategy("act1", "t", {})
        db.upsert_strategy("act2", "t", {})
        db.set_active_strategy("act1")
        assert db.get_active_strategy()["name"] == "act1"
        db.set_active_strategy("act2")
        assert db.get_active_strategy()["name"] == "act2"


class TestOrders:
    def test_insert_and_get(self):
        o = db.insert_order("AAPL", "buy", 10, 1500, "market")
        assert o["symbol"] == "AAPL"
        assert o["execution_status"] == "proposed"

    def test_update_order(self):
        o = db.insert_order("MSFT", "buy", 5, 500, "market")
        db.update_order(o["id"], risk_approved=1, risk_reason="approved", execution_status="risk_approved")
        updated = db.get_order(o["id"])
        assert updated["risk_approved"] is True
        assert updated["execution_status"] == "risk_approved"


class TestLogs:
    def test_insert_and_query(self):
        db.insert_log("test_cat", "test message", symbol="AAPL")
        logs = db.get_logs(category="test_cat")
        assert len(logs) >= 1
        assert logs[0]["symbol"] == "AAPL"

    def test_search(self):
        db.insert_log("search_cat", "findable keyword here")
        logs = db.get_logs(search="findable keyword")
        assert len(logs) >= 1


class TestDailyLedger:
    def test_get_default(self):
        ledger = db.get_daily_ledger()
        assert ledger["trade_count"] == 0

    def test_update_and_reset(self):
        db.update_daily_ledger(trade_count=5, realised_loss=100.0)
        ledger = db.get_daily_ledger()
        assert ledger["trade_count"] == 5
        db.reset_daily_ledger()
        ledger = db.get_daily_ledger()
        assert ledger["trade_count"] == 0


class TestSchemaMigrations:
    def test_schema_migrations_recorded(self):
        migrations = db.get_schema_migrations()
        versions = {m["version"] for m in migrations}
        assert "20260614_001_order_indexes" in versions
        assert "20260614_002_broker_order_event_indexes" in versions
        assert "20260614_003_reconciliation_runs" in versions

    def test_insert_broker_order_event(self):
        order = db.insert_order("AAPL", "buy", None, 5, "market", sizing_mode="notional", notional=5)
        event_id = db.insert_broker_order_event(
            order_id=order["id"],
            event_type="submit",
            status="paper_submitted",
            client_order_id="client-1",
            payload={"symbol": "AAPL", "notional": 5},
            response={"status": "paper_submitted"},
        )
        assert event_id > 0

    def test_reconciliation_run_persistence(self):
        run = db.insert_reconciliation_run(
            run_type="orders",
            status="mismatch",
            summary={"updated": 1},
            mismatches=[{"type": "status_changed"}],
        )
        assert run["id"] > 0
        assert run["summary"]["updated"] == 1
        assert run["mismatches"][0]["type"] == "status_changed"
        runs = db.get_reconciliation_runs(run_type="orders")
        assert any(r["id"] == run["id"] for r in runs)

    def test_exposure_helpers_sum_open_buys_and_positions(self):
        order = db.insert_order("AAPL", "buy", None, 7, "market", sizing_mode="notional", notional=7)
        db.update_order(order["id"], execution_status="risk_approved")
        closed = db.insert_order("MSFT", "buy", None, 99, "market", sizing_mode="notional", notional=99)
        db.update_order(closed["id"], execution_status="paper_filled")
        sell = db.insert_order("GOOGL", "sell", None, 50, "market", sizing_mode="notional", notional=50)
        db.update_order(sell["id"], execution_status="risk_approved")
        db.save_positions([{"symbol": "AAPL", "quantity": 0.1, "market_value": 12}], source="alpaca")
        assert db.get_open_order_exposure("stocks") >= 7
        assert db.get_position_exposure("alpaca") == 12


class TestBacktests:
    def test_insert_and_get(self):
        bt = db.insert_backtest("test_strat", ["AAPL"], "2024-01-01", "2024-06-01", 50000)
        assert bt["status"] == "pending"
        assert bt["symbols"] == ["AAPL"]
        fetched = db.get_backtest(bt["id"])
        assert fetched is not None


class TestAlpacaOrderFields:
    def test_insert_generic_broker_fields(self):
        order = db.insert_order(
            "AAPL",
            "buy",
            1,
            100,
            "market",
            broker="alpaca",
            paper=True,
            client_order_id="test-client-id",
            sizing_mode="notional",
            notional=100,
        )
        assert order["broker"] == "alpaca"
        assert order["paper"] is True
        assert order["client_order_id"] == "test-client-id"
        assert order["sizing_mode"] == "notional"
        assert order["notional"] == 100


class TestExposureService:
    def test_assigned_capital_counts_existing_exposure(self):
        order = db.insert_order("AAPL", "buy", None, 8, "market", sizing_mode="notional", notional=8)
        db.update_order(order["id"], execution_status="risk_approved")
        current = db.get_open_order_exposure() + db.get_position_exposure("alpaca")
        cfg = {
            "active_broker": "alpaca",
            "trading_mode": "simulation",
            "paper_trading": {"assigned_capital": current + 10, "use_assigned_capital_limit": True},
            "alpaca": {"mock_paper_submission": True},
        }
        approved, _, snapshot = ExposureService(cfg).approve_order_amount(5, side="buy")
        assert approved
        rejected, reason, _ = ExposureService(cfg).approve_order_amount(20, side="buy")
        assert not rejected
        assert "projected exposure" in reason
        assert snapshot["capital_source"] == "assigned_capital"


def teardown_module():
    os.unlink(_tmp.name)
