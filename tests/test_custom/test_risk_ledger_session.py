"""Tests for ET session-day ledger reset + PnL -> kill switch wiring (#7, #9)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from lumibot.custom_config.risk_engine import RiskEngine
from lumibot.custom_strategies.session import SessionClock

ET = ZoneInfo("America/New_York")


def _cfg(**overrides):
    cfg = {
        "active_broker": "alpaca",
        "active_data_provider": "alpaca",
        "default_asset_class": "stocks",
        "trading_mode": "paper",
        "live_trading_enabled": False,
        "active_asset_classes": ["stocks"],
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "stocks": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                   "sizing_mode": "notional", "max_order_notional": 100000},
        "watchlist": {"stocks": ["AAPL"]},
        "risk_limits": {"max_dollars_per_trade": 100000, "max_loss_per_trade": 25,
                        "max_daily_loss": 100, "max_trades_per_day": 100, "max_open_positions": 100},
        "stocks_in_play_orb_v1": {},
    }
    cfg.update(overrides)
    return cfg


class TestSessionDayReset:
    def test_reset_on_new_et_day(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        engine = RiskEngine(_cfg(), clock=clock)
        engine.record_trade(loss=10)
        assert engine.ledger_snapshot()["trade_count"] == 1

        # Advance the clock to the next ET day; the next approval should reset counters.
        engine._clock = SessionClock(now_provider=lambda: datetime(2026, 6, 16, 5, 0, tzinfo=ET))
        engine.approve_proposal("AAPL", 50)
        snap = engine.ledger_snapshot()
        assert snap["trade_count"] == 0
        assert snap["realised_loss"] == 0.0
        assert snap["trade_date"] == "2026-06-16"

    def test_extended_hours_same_session_day(self):
        # Pre-market and after-hours of the same ET date share one session day.
        pre = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 5, 0, tzinfo=ET))
        post = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 18, 0, tzinfo=ET))
        assert pre.session_day() == post.session_day()


class TestPnLKillSwitch:
    def test_realized_loss_engages_kill_switch(self):
        engine = RiskEngine(_cfg(risk_limits={"max_dollars_per_trade": 100000, "max_loss_per_trade": 25,
                                              "max_daily_loss": 50, "max_trades_per_day": 100,
                                              "max_open_positions": 100}))
        engine.record_fill_pnl(-60)  # exceeds 50 daily loss limit
        assert engine.kill_switch_active
        assert "DAILY_LOSS_BREACHED" in engine.kill_switch_reasons

    def test_kill_switch_blocks_new_orders(self):
        engine = RiskEngine(_cfg(risk_limits={"max_dollars_per_trade": 100000, "max_loss_per_trade": 25,
                                              "max_daily_loss": 50, "max_trades_per_day": 100,
                                              "max_open_positions": 100}))
        engine.record_fill_pnl(-60)
        approved, reason = engine.approve_proposal("AAPL", 10)
        assert not approved
        assert "kill switch" in reason or "daily loss" in reason

    def test_profit_does_not_engage(self):
        engine = RiskEngine(_cfg())
        engine.record_fill_pnl(100)
        assert not engine.kill_switch_active

    def test_manual_engage_and_reset(self):
        engine = RiskEngine(_cfg())
        engine.engage_kill_switch("MANUAL")
        assert engine.kill_switch_active
        approved, _ = engine.approve_proposal("AAPL", 1)
        assert not approved
        engine.reset_kill_switch()
        assert not engine.kill_switch_active

    def test_sync_ledger_reengages_kill_switch(self):
        engine = RiskEngine(_cfg(risk_limits={"max_dollars_per_trade": 100000, "max_loss_per_trade": 25,
                                              "max_daily_loss": 50, "max_trades_per_day": 100,
                                              "max_open_positions": 100}))
        engine.sync_ledger(trade_count=3, realised_loss=75.0)
        assert engine.kill_switch_active


class TestProtectiveKillSwitch:
    """The kill switch must halt new entries but never block risk-reducing exits."""

    def test_allows_new_entries_flips_with_kill_switch(self):
        engine = RiskEngine(_cfg())
        assert engine.allows_new_entries is True
        engine.engage_kill_switch("MANUAL")
        assert engine.allows_new_entries is False

    def test_approve_exit_allowed_when_kill_switch_active(self):
        engine = RiskEngine(_cfg())
        engine.engage_kill_switch("DAILY_LOSS_BREACHED")
        # Entries blocked...
        entry_ok, _ = engine.approve_proposal("AAPL", 10)
        assert entry_ok is False
        # ...but exits always allowed so the bot can get flat.
        exit_ok, reason = engine.approve_exit("AAPL", 1000)
        assert exit_ok is True
        assert "exit" in reason.lower()

    def test_approve_exit_not_gated_by_daily_loss_or_caps(self):
        engine = RiskEngine(_cfg(risk_limits={"max_dollars_per_trade": 1, "max_loss_per_trade": 1,
                                              "max_daily_loss": 1, "max_trades_per_day": 0,
                                              "max_open_positions": 0}))
        # A huge exit notional that would fail every entry gate is still approved.
        ok, _ = engine.approve_exit("AAPL", 999999)
        assert ok is True
