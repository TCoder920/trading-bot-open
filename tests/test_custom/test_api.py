"""Tests for the FastAPI backend endpoints."""

import os
import tempfile

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()

import backend.database as db
from pathlib import Path
db.DB_PATH = Path(_tmp.name)
db.init_db()

import backend.state as state
state._config = None

from backend.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_execution_safety(monkeypatch):
    """Keep live trading disabled between tests; avoids user_config.yaml pollution."""
    monkeypatch.setenv("TRADING_MODE", "simulation")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("ALPACA_IS_PAPER", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_API_SECRET", "")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "")
    monkeypatch.setenv("ALPACA_LIVE_API_KEY", "")
    monkeypatch.setenv("ALPACA_LIVE_API_SECRET", "")
    monkeypatch.setenv("ALPACA_OAUTH_TOKEN", "")
    state._config = None
    client.patch("/api/config/batch", json={
        "updates": {
            "live_trading_enabled": False,
            "trading_mode": "simulation",
            "paper_trading.assigned_capital": None,
            "paper_trading.use_assigned_capital_limit": False,
            "stocks.sizing_mode": "notional",
            "stocks.min_order_notional": 1,
            "stocks.max_order_notional": None,
            "risk_limits.max_daily_loss": 200,
            "risk_limits.max_open_positions": 5,
        },
    })
    state._config = None
    yield


class TestHealth:
    def test_health(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestConfig:
    def test_read_config(self):
        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json()["active_broker"] == "alpaca"
        assert r.json()["active_data_provider"] == "alpaca"
        assert r.json()["trading_mode"] == "simulation"

    def test_live_trading_disabled_by_default(self):
        r = client.get("/api/config")
        assert r.json()["live_trading_enabled"] is False

    def test_assigned_capital_defaults(self):
        r = client.get("/api/config")
        cfg = r.json()
        assert cfg["paper_trading"]["assigned_capital"] is None
        assert cfg["paper_trading"]["use_assigned_capital_limit"] is False
        assert cfg["stocks"]["sizing_mode"] == "notional"

    def test_update_config(self):
        r = client.patch("/api/config", json={"key": "active_asset_class", "value": "stocks"})
        assert r.status_code == 200

    def test_batch_config_update(self):
        r = client.patch("/api/config/batch", json={
            "updates": {
                "require_order_review": True,
                "default_data_source": "alpaca",
            },
        })
        assert r.status_code == 200
        cfg = client.get("/api/config").json()
        assert cfg["require_order_review"] is True
        assert cfg["default_data_source"] == "alpaca"

    def test_config_validation_endpoint(self):
        r = client.get("/api/config/validation")
        assert r.status_code == 200
        assert "live_trading_ready" in r.json()

    def test_reload_config(self):
        r = client.post("/api/config/reload")
        assert r.status_code == 200

    def test_cannot_enable_live_in_simulation(self):
        client.patch("/api/config", json={"key": "trading_mode", "value": "simulation"})
        state._config = None
        state.get_config()
        r = client.patch("/api/config", json={"key": "live_trading_enabled", "value": True})
        assert r.status_code == 400

    def test_live_trading_blocked_without_alpaca_credentials(self):
        client.patch("/api/config/batch", json={
            "updates": {
                "trading_mode": "live",
                "live_trading_enabled": False,
            },
        })
        state._config = None
        state.get_config()
        r = client.patch("/api/config", json={"key": "live_trading_enabled", "value": True})
        assert r.status_code == 400

    def test_paper_mode_blocked_without_alpaca_credentials(self):
        client.patch("/api/config/batch", json={
            "updates": {
                "trading_mode": "paper",
                "live_trading_enabled": False,
            },
        })
        r = client.post("/api/config/validate-draft", json={"updates": {"trading_mode": "paper", "mock_paper_submission": False}})
        assert r.status_code == 200
        assert r.json()["errors"]

    def test_validate_draft_live_trading(self):
        r = client.post("/api/config/validate-draft", json={
            "updates": {
                "trading_mode": "live",
                "live_trading_enabled": True,
            },
        })
        assert r.status_code == 200
        assert r.json()["live_trading_ready"] is False

    def test_batch_live_trading_rejected_without_credentials(self):
        r = client.patch("/api/config/batch", json={
            "updates": {
                "trading_mode": "live",
                "live_trading_enabled": True,
            },
        })
        assert r.status_code == 400


class TestRisk:
    def test_read_risk_settings(self):
        r = client.get("/api/risk/settings")
        assert r.status_code == 200
        assert "max_dollars_per_trade" in r.json()

    def test_update_risk_settings(self):
        r = client.patch("/api/risk/settings", json={"max_dollars_per_trade": 200})
        assert r.status_code == 200
        assert r.json()["max_dollars_per_trade"] == 200

    def test_update_assigned_capital_settings_affects_order_risk(self):
        r = client.patch("/api/risk/settings", json={
            "assigned_capital": 50,
            "use_assigned_capital_limit": True,
            "max_stock_order_notional": 75,
            "max_dollars_per_trade": 100,
        })
        assert r.status_code == 200
        assert r.json()["assigned_capital"] == 50
        order = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "asset_class": "stocks", "notional": 60,
        })
        assert order.status_code == 200
        assert order.json()["risk_approved"] is False
        assert "assigned_capital" in order.json()["risk_reason"]

    def test_blank_assigned_capital_does_not_cap_order(self):
        client.patch("/api/risk/settings", json={
            "assigned_capital": None,
            "use_assigned_capital_limit": True,
            "max_stock_order_notional": 75,
            "max_dollars_per_trade": 100,
        })
        order = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "asset_class": "stocks", "notional": 10,
        })
        assert order.status_code == 200
        assert order.json()["risk_approved"] is True


class TestWatchlist:
    def test_add_symbol(self):
        r = client.post("/api/watchlist", json={"symbol": "NVDA", "asset_class": "stocks"})
        assert r.status_code == 200

    def test_read_watchlist(self):
        r = client.get("/api/watchlist?asset_class=stocks")
        assert r.status_code == 200
        assert "NVDA" in r.json()["symbols"]

    def test_remove_symbol(self):
        client.post("/api/watchlist", json={"symbol": "RMSYM"})
        r = client.request("DELETE", "/api/watchlist", json={"symbol": "RMSYM"})
        assert r.status_code == 200


class TestStrategies:
    def test_list_templates(self):
        r = client.get("/api/strategies/templates")
        assert r.status_code == 200
        assert "moving_average_crossover" in r.json()

    def test_create_strategy(self):
        r = client.post("/api/strategies", json={
            "name": "my_ma",
            "template": "moving_average_crossover",
            "config": {"fast_period": 5},
        })
        assert r.status_code == 200
        assert r.json()["name"] == "my_ma"

    def test_update_strategy(self):
        client.post("/api/strategies", json={"name": "upd_s", "template": "rsi_mean_reversion"})
        r = client.patch("/api/strategies/upd_s", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_delete_strategy(self):
        client.post("/api/strategies", json={"name": "del_s", "template": "buy_and_hold"})
        r = client.delete("/api/strategies/del_s")
        assert r.status_code == 200

    def test_activate_strategy(self):
        client.post("/api/strategies", json={"name": "act_s", "template": "buy_and_hold"})
        r = client.post("/api/strategies/act_s/activate")
        assert r.status_code == 200
        assert r.json()["is_active"] is True


class TestOrders:
    def test_list_orders_empty(self):
        r = client.get("/api/orders")
        assert r.status_code == 200
        assert "orders" in r.json()
        assert isinstance(r.json()["orders"], list)

    def test_propose_order_risk_rejected(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 500,
        })
        assert r.status_code == 200
        assert r.json()["risk_approved"] is False

    def test_propose_order_risk_approved_simulation(self):
        client.patch("/api/risk/settings", json={"max_dollars_per_trade": 200})
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 5,
        })
        assert r.status_code == 200
        assert r.json()["risk_approved"] is True
        assert r.json()["sizing_mode"] == "notional"
        assert r.json()["notional"] == 5
        assert r.json()["quantity"] is None
        assert r.json()["time_in_force"] == "day"
        assert r.json()["execution_status"] in ("risk_approved", "pending_broker_submission")

    def test_preview_stock_notional_order(self):
        r = client.post("/api/orders/preview", json={
            "symbol": "AAPL", "side": "buy", "asset_class": "stocks", "notional": 5,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert body["risk_approved"] is True
        assert body["normalized"]["sizing_mode"] == "notional"
        assert body["broker_payload"]["notional"] == 5
        assert "qty" not in body["broker_payload"]

    def test_reject_stock_order_with_quantity_and_notional(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "asset_class": "stocks", "quantity": 1, "notional": 5,
        })
        assert r.status_code == 400
        assert "both quantity and notional" in r.json()["detail"]

    def test_propose_stock_whole_share_order(self):
        client.patch("/api/risk/settings", json={
            "assigned_capital": 200,
            "max_stock_order_notional": 200,
            "max_dollars_per_trade": 200,
        })
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL",
            "side": "buy",
            "asset_class": "stocks",
            "sizing_mode": "whole_share",
            "quantity": 1,
            "dollar_amount": 150,
        })
        assert r.status_code == 200
        assert r.json()["risk_approved"] is True
        assert r.json()["sizing_mode"] == "whole_share"
        assert r.json()["quantity"] == 1
        assert r.json()["notional"] is None

    def test_reject_stock_fractional_quantity(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL",
            "side": "buy",
            "asset_class": "stocks",
            "sizing_mode": "whole_share",
            "quantity": 1.5,
            "dollar_amount": 5,
        })
        assert r.status_code == 400
        assert "whole-share" in r.json()["detail"]

    def test_reject_non_fractionable_stock_notional(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "NOFRAC", "side": "buy", "asset_class": "stocks", "notional": 5,
        })
        assert r.status_code == 400
        assert "not fractionable" in r.json()["detail"]

    def test_reject_options_notional_order(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL260116C00200000", "side": "buy", "asset_class": "options", "notional": 5,
        })
        assert r.status_code == 400
        assert "Options orders cannot use notional" in r.json()["detail"]

    def test_reject_options_fractional_quantity(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL260116C00200000", "side": "buy", "asset_class": "options", "quantity": 1.5,
        })
        assert r.status_code == 400
        assert "whole contract" in r.json()["detail"]

    def test_order_workflow_advance_execute(self):
        client.patch("/api/risk/settings", json={"max_dollars_per_trade": 200})
        client.patch("/api/config", json={"key": "require_order_review", "value": True})
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 5,
        })
        order_id = r.json()["id"]
        assert r.json()["execution_status"] == "risk_approved"

        r2 = client.post(f"/api/orders/{order_id}/advance")
        assert r2.status_code == 200
        assert r2.json()["execution_status"] == "pending_broker_submission"

        r3 = client.post(f"/api/orders/{order_id}/execute", json={"notes": "test"})
        assert r3.status_code == 200
        assert r3.json()["execution_status"] == "paper_filled"

    def test_terminal_order_cannot_transition(self):
        client.patch("/api/risk/settings", json={"max_dollars_per_trade": 200})
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 5,
        })
        order_id = r.json()["id"]
        client.post(f"/api/orders/{order_id}/advance")
        client.post(f"/api/orders/{order_id}/execute", json={"notes": "test"})
        r2 = client.post(f"/api/orders/{order_id}/cancel")
        assert r2.status_code == 400

    def test_review_requires_risk_approval(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 500,
        })
        order_id = r.json()["id"]
        r2 = client.post(f"/api/orders/{order_id}/review")
        assert r2.status_code == 400

    def test_place_blocked_when_live_disabled(self):
        client.patch("/api/risk/settings", json={"max_dollars_per_trade": 200})
        r = client.post("/api/orders/propose", json={
            "symbol": "AAPL", "side": "buy", "dollar_amount": 5,
        })
        order_id = r.json()["id"]
        client.post(f"/api/orders/{order_id}/advance")
        r2 = client.post(f"/api/orders/{order_id}/place")
        data = client.get(f"/api/orders/{order_id}").json()
        assert data["execution_status"] == "accepted"


class TestBot:
    def test_bot_status(self):
        r = client.get("/api/bot/status")
        assert r.status_code == 200
        assert "bot_state" in r.json()

    def test_reset_ledger(self):
        r = client.post("/api/bot/ledger/reset")
        assert r.status_code == 200
        assert r.json()["trade_count"] == 0


class TestBacktest:
    def test_list_backtests(self):
        r = client.get("/api/backtests")
        assert r.status_code == 200


class TestAlpaca:
    def test_alpaca_status(self):
        r = client.get("/api/alpaca/status")
        assert r.status_code == 200
        assert r.json()["broker"] == "alpaca"

    def test_alpaca_credentials(self):
        r = client.get("/api/alpaca/credentials")
        assert r.status_code == 200
        assert "configured" in r.json()

    def test_asset_classes(self):
        r = client.get("/api/assets/classes")
        assert r.status_code == 200
        classes = {c["asset_class"]: c for c in r.json()["asset_classes"]}
        assert classes["stocks"]["enabled"] is True
        assert classes["options"]["live_enabled"] is False
        assert classes["crypto"]["live_enabled"] is False


class TestReconciliation:
    def test_exposure_snapshot_endpoint(self):
        r = client.get("/api/reconciliation/exposure")
        assert r.status_code == 200
        body = r.json()
        assert "capital_source" in body
        assert "open_order_exposure" in body
        assert body["assigned_capital_enabled"] is False

    def test_reconciliation_runs_endpoint(self):
        r = client.get("/api/reconciliation/runs")
        assert r.status_code == 200
        assert "runs" in r.json()

    def test_positions_sync_handles_missing_credentials(self):
        r = client.post("/api/reconciliation/positions")
        assert r.status_code == 200
        assert r.json()["status"] == "not_configured"

    def test_order_reconcile_handles_missing_credentials(self):
        r = client.post("/api/reconciliation/orders")
        assert r.status_code == 200
        assert r.json()["status"] == "not_configured"


class TestSystem:
    def test_system_readiness(self):
        r = client.get("/api/system/readiness")
        assert r.status_code == 200
        body = r.json()
        assert "checks" in body
        assert "schema_migrations" in body

    def test_system_backup(self):
        r = client.post("/api/system/backup")
        assert r.status_code == 200
        assert r.json()["backup"]["path"]


class TestLogs:
    def test_read_logs(self):
        r = client.get("/api/logs")
        assert r.status_code == 200
        assert "logs" in r.json()


class TestExecutionModeValidation:
    def test_unsupported_asset_class_via_order(self):
        r = client.post("/api/orders/propose", json={
            "symbol": "BTCUSD", "side": "buy", "dollar_amount": 5,
            "asset_class": "crypto",
        })
        assert r.status_code == 200
        assert r.json()["risk_approved"] is False
        reason = r.json()["risk_reason"]
        assert "requires explicit enablement" in reason


class TestIndicators:
    def test_list_indicators(self):
        r = client.get("/api/indicators")
        assert r.status_code == 200
        assert len(r.json()["indicators"]) >= 10


def teardown_module():
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
