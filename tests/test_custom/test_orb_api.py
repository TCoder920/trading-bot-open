"""Integration tests for the ORB backend routes and strategy wiring."""

import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()

import backend.database as db
db.DB_PATH = Path(_tmp.name)
db.init_db()

import backend.state as state
state._config = None

from backend.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def _green_or():
    return [
        {"open": 98.5, "high": 99.0, "low": 98.0, "close": 98.9, "volume": 50000},
        {"open": 98.9, "high": 100.0, "low": 98.1, "close": 99.9, "volume": 60000},
    ]


def _snapshot(symbol="AAPL", price=101.0):
    return {
        "symbol": symbol,
        "opening_range_bars": _green_or(),
        "session_bars": [{"open": 99, "high": 101, "low": 98.5, "close": 100.5, "volume": 100000}],
        "price": price,
        "bid": price - 0.01,
        "ask": price + 0.01,
        "atr_14": 2.0,
        "rvol": 3.0,
        "avg_volume": 5_000_000,
        "data_fresh": True,
    }


@pytest.fixture(autouse=True)
def _reset():
    state._config = None
    yield


class TestOrbTemplate:
    def test_orb_template_listed(self):
        r = client.get("/api/strategies/templates")
        assert r.status_code == 200
        assert "stocks_in_play_orb_v1" in r.json()
        tmpl = r.json()["stocks_in_play_orb_v1"]
        assert tmpl["long_only"] is True
        assert "rvol_min" in tmpl["default_config"]
        assert "param_help" in tmpl

    def test_create_activate_orb_strategy(self):
        r = client.post("/api/strategies", json={
            "name": "orb_test",
            "template": "stocks_in_play_orb_v1",
            "config": {"rvol_min": 2.5, "top_candidates": 5},
        })
        assert r.status_code == 200
        assert r.json()["config"]["rvol_min"] == 2.5
        a = client.post("/api/strategies/orb_test/activate")
        assert a.status_code == 200
        assert a.json()["is_active"] is True


class TestOrbConfigAndStatus:
    def test_orb_config(self):
        r = client.get("/api/orb/config")
        assert r.status_code == 200
        assert r.json()["strategy_id"] == "stocks_in_play_orb_v1"
        assert "rvol_min" in r.json()["config"]

    def test_orb_status_empty(self):
        client.post("/api/orb/reset")
        r = client.get("/api/orb/status")
        assert r.status_code == 200
        assert "candidate_count" in r.json()


class TestOrbGenerate:
    def test_generate_pending_proposal(self):
        # widen watchlist so AAPL is allowed and risk passes
        client.post("/api/watchlist", json={"symbol": "AAPL", "asset_class": "stocks"})
        client.post("/api/orb/reset")
        r = client.post("/api/orb/generate", json={
            "snapshots": [_snapshot("AAPL", 101.0)],
            "regime_state": "risk_on",
            "equity": 100000,
            "now_time": "09:40",
        })
        assert r.status_code == 200
        body = r.json()
        assert "AAPL" in body["candidates"]
        statuses = [p["status"] for p in body["proposals"]]
        assert "pending" in statuses

    def test_generate_rejects_below_vwap(self):
        client.post("/api/orb/reset")
        snap = _snapshot("AAPL", 101.0)
        snap["session_bars"] = [{"open": 102, "high": 103, "low": 101.5, "close": 102.5, "volume": 100000}]
        r = client.post("/api/orb/generate", json={
            "snapshots": [snap], "regime_state": "risk_on", "equity": 100000, "now_time": "09:40",
        })
        assert r.status_code == 200
        # price 101 below vwap (~102.16) -> rejected
        assert any(p["status"] == "rejected" for p in r.json()["proposals"])


class TestOrbPromote:
    def test_promote_to_order(self):
        client.post("/api/watchlist", json={"symbol": "AAPL", "asset_class": "stocks"})
        client.patch("/api/risk/settings", json={
            "max_dollars_per_trade": 1_000_000,
            "assigned_capital": 1_000_000,
            "max_stock_order_notional": 1_000_000,
        })
        client.post("/api/orb/reset")
        gen = client.post("/api/orb/generate", json={
            "snapshots": [_snapshot("AAPL", 101.0)],
            "regime_state": "risk_on", "equity": 100000, "now_time": "09:40",
        })
        pending = [p for p in gen.json()["proposals"] if p["status"] == "pending"]
        assert pending, "expected a pending proposal to promote"
        pid = pending[0]["id"]
        r = client.post(f"/api/orb/proposals/{pid}/promote")
        assert r.status_code == 200
        assert r.json()["risk_approved"] is True
        # linked order exists and is in the Alpaca workflow
        oid = r.json()["order"]
        order = client.get(f"/api/orders/{oid}").json()
        assert order["strategy"] == "stocks_in_play_orb_v1"
        assert order["sizing_mode"] == "whole_share"
        assert order["quantity"] >= 1
        assert order["execution_status"] in ("risk_approved", "pending_broker_submission")

    def test_cannot_promote_twice(self):
        client.post("/api/watchlist", json={"symbol": "AAPL", "asset_class": "stocks"})
        client.patch("/api/risk/settings", json={
            "max_dollars_per_trade": 1_000_000,
            "assigned_capital": 1_000_000,
            "max_stock_order_notional": 1_000_000,
        })
        client.post("/api/orb/reset")
        gen = client.post("/api/orb/generate", json={
            "snapshots": [_snapshot("AAPL", 101.0)],
            "regime_state": "risk_on", "equity": 100000, "now_time": "09:40",
        })
        pending = [p for p in gen.json()["proposals"] if p["status"] == "pending"]
        pid = pending[0]["id"]
        client.post(f"/api/orb/proposals/{pid}/promote")
        r2 = client.post(f"/api/orb/proposals/{pid}/promote")
        assert r2.status_code == 400


class TestOrbDiagnosticsAndReconcile:
    def test_diagnostics(self):
        r = client.get("/api/orb/diagnostics")
        assert r.status_code == 200
        assert "rejection_reasons" in r.json()

    def test_reconcile_mismatch_flags_kill(self):
        r = client.post("/api/orb/reconcile", json={
            "internal": [{"symbol": "AAPL", "quantity": 10}],
            "broker": [{"symbol": "AAPL", "quantity": 0}],
            "tolerance": 0,
        })
        assert r.status_code == 200
        assert r.json()["kill_switch_recommended"] is True

    def test_flatten_scaffold(self):
        r = client.post("/api/orb/flatten")
        assert r.status_code == 200
        assert r.json()["status"] == "flatten_requested"


class TestOrbReset:
    def test_reset(self):
        r = client.post("/api/orb/reset")
        assert r.status_code == 200
        assert "cleared_pending_proposals" in r.json()


class TestOrbBacktestWiring:
    """Verify ORB is dispatched in the backtest worker without spawning a real
    network-bound run (which would race the test teardown)."""

    def test_template_dispatch(self):
        from backend.routes.backtest import ORB_TEMPLATE, _resolve_template
        bt = {"strategy_name": "stocks_in_play_orb_v1", "symbols": ["AAPL"]}
        template, _cfg = _resolve_template(bt)
        assert template == ORB_TEMPLATE

    def test_template_dispatch_from_saved_strategy(self):
        client.post("/api/strategies", json={
            "name": "orb_bt", "template": "stocks_in_play_orb_v1", "config": {},
        })
        from backend.routes.backtest import ORB_TEMPLATE, _resolve_template
        template, cfg = _resolve_template({"strategy_name": "orb_bt", "symbols": ["AAPL"]})
        assert template == ORB_TEMPLATE
        assert "rvol_min" in cfg

    def test_orb_metrics_computation(self):
        from backend.routes.backtest import _orb_metrics
        trades = [
            {"entry_price": 100, "exit_price": 106, "stop_price": 98, "quantity": 10, "pnl": 60},
            {"entry_price": 50, "exit_price": 48, "stop_price": 47, "quantity": 10, "pnl": -20},
        ]
        proposals = [{"status": "pending", "rvol": 3.0, "spread": 0.02}]
        m = _orb_metrics(trades, proposals, 100000)
        assert m["total_trades"] == 2
        assert m["win_rate_pct"] == 50.0
        assert m["best_trade"] == 60
        assert m["worst_trade"] == -20
        assert m["ending_equity"] == 100040


def teardown_module():
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass
