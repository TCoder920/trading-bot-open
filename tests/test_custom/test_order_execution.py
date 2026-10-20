"""Tests for idempotent, session-aware order execution (#2, #3, #4, #9)."""

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


from backend.services.alpaca_service import AlpacaService  # noqa: E402
from backend.services.order_execution import OrderExecutionService  # noqa: E402
from lumibot.custom_config.risk_engine import RiskEngine  # noqa: E402
from lumibot.custom_strategies.session import SessionClock  # noqa: E402


def _cfg(**overrides):
    cfg = {
        "active_broker": "alpaca",
        "active_data_provider": "alpaca",
        "default_asset_class": "stocks",
        "trading_mode": "paper",
        "live_trading_enabled": False,
        "active_asset_classes": ["stocks"],
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "alpaca": {"enabled": True, "allow_extended_hours": False, "marketable_limit_offset_pct": 0.2,
                   "mock_paper_submission": True},
        "stocks": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                   "sizing_mode": "notional", "max_order_notional": 1000000},
        "watchlist": {"stocks": ["AAPL"]},
        "risk_limits": {"max_dollars_per_trade": 1000000, "max_loss_per_trade": 1000,
                        "max_daily_loss": 100000, "max_trades_per_day": 1000, "max_open_positions": 1000},
        "stocks_in_play_orb_v1": {"tick_size": 0.01},
    }
    cfg.update(overrides)
    return cfg


class FakeBroker:
    def __init__(self):
        self.submitted = []

    def submit_order(self, order):
        self.submitted.append(order)
        return {
            "status": "paper_submitted", "execution_status": "paper_submitted",
            "broker_order_id": f"bo-{len(self.submitted)}",
            "client_order_id": order["client_order_id"], "paper": True,
            "details": {"payload": order},
        }


def _service(cfg, clock):
    risk = RiskEngine(cfg, clock=clock)
    return OrderExecutionService(cfg, broker=FakeBroker(), risk=risk, clock=clock), risk


class TestIdempotency:
    def test_duplicate_submit_is_skipped(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        svc, _ = _service(_cfg(), clock)
        r1 = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                               reference_price=100.0, stop_price=101.0, role="entry")
        assert r1.status == "paper_submitted"
        r2 = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                               reference_price=100.0, stop_price=101.0, role="entry")
        assert r2.idempotent
        assert r2.status == "duplicate"
        assert r2.order_id == r1.order_id
        # Only one order row exists.
        assert len(db.get_orders(limit=50)) == 1


class TestSessionGating:
    def test_extended_hours_blocked_when_disabled(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 5, 0, tzinfo=ET))
        svc, _ = _service(_cfg(), clock)
        r = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                              reference_price=100.0, stop_price=101.0, role="entry")
        assert r.status == "skipped"
        assert "extended hours" in r.reason

    def test_market_closed_skips(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 23, 0, tzinfo=ET))
        svc, _ = _service(_cfg(), clock)
        r = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                              reference_price=100.0, stop_price=101.0, role="entry")
        assert r.status == "skipped"

    def test_extended_hours_uses_marketable_limit(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 5, 0, tzinfo=ET))
        cfg = _cfg(alpaca={"enabled": True, "allow_extended_hours": True,
                           "marketable_limit_offset_pct": 0.5, "mock_paper_submission": True})
        svc, _ = _service(cfg, clock)
        r = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                              reference_price=100.0, stop_price=101.0, role="entry")
        assert r.status == "paper_submitted"
        assert r.order_spec["order_type"] == "limit"
        assert r.order_spec["extended_hours"] is True
        assert r.order_spec["limit_price"] == pytest.approx(100.5)


class TestKillSwitchBlocks:
    def test_kill_switch_blocks_submission(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        svc, risk = _service(_cfg(), clock)
        risk.engage_kill_switch("MANUAL")
        r = svc.submit_intent(symbol="AAPL", side="buy", quantity=10, intent="stop",
                              reference_price=100.0, stop_price=101.0, role="entry")
        assert r.status == "blocked"
        assert db.get_orders(limit=50) == []

    def test_kill_switch_allows_exit_sell(self):
        # Risk-reducing exits must still go through so the bot can flatten.
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        svc, risk = _service(_cfg(), clock)
        risk.engage_kill_switch("DAILY_LOSS_BREACHED")
        r = svc.submit_intent(symbol="AAPL", side="sell", quantity=10, intent="market",
                              reference_price=100.0, role="flatten")
        assert r.status == "paper_submitted"


class TestPreparePayloadExtendedHours:
    """The extended_hours flag must plumb through prepare_order_payload (#2)."""

    def test_extended_hours_limit_payload(self):
        svc = AlpacaService(_cfg())
        payload = svc.prepare_order_payload({
            "id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
            "order_type": "limit", "time_in_force": "day", "extended_hours": True,
            "limit_price": 100.5, "quantity": 10, "sizing_mode": "whole_share",
        })
        assert payload["extended_hours"] is True
        assert payload["type"] == "limit"
        assert payload["limit_price"] == 100.5

    def test_extended_hours_rejects_market(self):
        svc = AlpacaService(_cfg())
        with pytest.raises(ValueError):
            svc.prepare_order_payload({
                "id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
                "order_type": "market", "time_in_force": "day", "extended_hours": True,
                "quantity": 10, "sizing_mode": "whole_share",
            })

    def test_extended_hours_requires_limit_price(self):
        svc = AlpacaService(_cfg())
        with pytest.raises(ValueError):
            svc.prepare_order_payload({
                "id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
                "order_type": "limit", "time_in_force": "day", "extended_hours": True,
                "quantity": 10, "sizing_mode": "whole_share",
            })


class TestRealVsMockGating:
    def test_simulation_is_mocked(self):
        svc = AlpacaService(_cfg(trading_mode="simulation"))
        result = svc.submit_order({"id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
                                   "quantity": 1, "order_type": "market", "sizing_mode": "whole_share"})
        assert result["details"]["mode"] == "simulation"

    def test_paper_mock_when_enabled(self):
        svc = AlpacaService(_cfg(trading_mode="paper"))
        result = svc.submit_order({"id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
                                   "quantity": 1, "order_type": "market", "sizing_mode": "whole_share"})
        assert result["details"]["mocked"] is True
        assert result["broker_order_id"].startswith("paper-mock-")

    def test_real_paper_requires_credentials(self, monkeypatch):
        # mock off + no creds => must fail clearly, never silently no-op and never
        # reach the network. Clear all Alpaca env credentials for this assertion.
        for var in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_OAUTH_TOKEN",
                    "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET",
                    "ALPACA_LIVE_API_KEY", "ALPACA_LIVE_API_SECRET"):
            monkeypatch.delenv(var, raising=False)
        cfg = _cfg(trading_mode="paper",
                   alpaca={"enabled": True, "allow_extended_hours": False,
                           "marketable_limit_offset_pct": 0.2, "mock_paper_submission": False})
        svc = AlpacaService(cfg)
        result = svc.submit_order({"id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks",
                                   "quantity": 1, "order_type": "market", "sizing_mode": "whole_share"})
        assert result["status"] == "failed"
        assert any("credentials" in e for e in result["errors"])
