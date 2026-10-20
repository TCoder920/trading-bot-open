"""Tests for the autonomous loop orchestration (#1, #5, #7, #8, #10, #11)."""

import tempfile
from datetime import datetime, time
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


from backend.services.autonomous_runner import AutonomousRunner  # noqa: E402
from backend.services.order_execution import ExecutionResult  # noqa: E402
from lumibot.custom_config.risk_engine import RiskEngine  # noqa: E402
from lumibot.custom_strategies.session import SessionClock  # noqa: E402


def _cfg(**overrides):
    cfg = {
        "active_broker": "alpaca", "active_data_provider": "alpaca", "default_asset_class": "stocks",
        "trading_mode": "paper", "live_trading_enabled": False, "active_asset_classes": ["stocks"],
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "alpaca": {"enabled": True, "allow_extended_hours": False, "marketable_limit_offset_pct": 0.2,
                   "mock_paper_submission": True},
        "stocks": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                   "sizing_mode": "notional", "max_order_notional": 1000000},
        "watchlist": {"stocks": ["AAPL"]},
        "risk_limits": {"max_dollars_per_trade": 1000000, "max_loss_per_trade": 1000,
                        "max_daily_loss": 100000, "max_trades_per_day": 1000, "max_open_positions": 1000},
        "stocks_in_play_orb_v1": {
            "opening_range_start": "09:30", "opening_range_end": "09:35",
            "entry_window_start": "09:35", "entry_window_end": "10:30",
            "flatten_time": "15:45", "rvol_min": 2.0, "require_above_vwap": True,
            "enable_spy_regime_filter": True, "atr_stop_factor": 0.15,
            "risk_per_trade_pct": 0.25, "tick_size": 0.01, "extended_hours_signals": "rth_only",
            "premarket_session_start": "04:00", "rth_end": "16:00", "postmarket_session_end": "20:00",
        },
    }
    cfg.update(overrides)
    return cfg


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit_intent(self, **kwargs):
        self.calls.append(kwargs)
        return ExecutionResult("paper_submitted", "ok", order_id=len(self.calls),
                               client_order_id=f"coid-{len(self.calls)}",
                               order_spec={"order_type": "limit"})


class FakeReconciler:
    def __init__(self, kill=False):
        self.kill = kill

    def reconcile(self):
        return {"status": "ok", "kill_switch_active": self.kill}


class FakeMarketData:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def snapshots(self, symbols, *, extended_hours=False):
        from backend.services.market_data import MarketDataResult

        wanted = {s.upper() for s in symbols}
        return MarketDataResult(snapshots=[s for s in self._snapshots if s["symbol"].upper() in wanted])


def _entry_snapshot():
    or_bars = [{"time": time(9, 30), "open": 100.0, "high": 101.0, "low": 99.5,
                "close": 100.5, "volume": 500000}]
    session_bars = or_bars + [
        {"time": time(9, 40), "open": 100.5, "high": 101.5, "low": 100.4, "close": 101.0, "volume": 300000},
    ]
    return {
        "symbol": "AAPL", "opening_range_bars": or_bars, "session_bars": session_bars,
        "price": 102.0, "bid": 101.95, "ask": 102.0, "rvol": 3.0,
        "in_watchlist": True, "data_fresh": True,
    }


def _runner(cfg, *, clock, market_data, executor=None, reconciler=None, equity=100000.0):
    risk = RiskEngine(cfg, clock=clock)
    return AutonomousRunner(
        cfg, clock=clock, risk=risk,
        market_data=market_data,
        executor=executor or FakeExecutor(),
        reconciler=reconciler or FakeReconciler(),
        equity_provider=lambda: equity,
    )


class TestSessionGating:
    def test_closed_session_does_not_run(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 23, 0, tzinfo=ET))
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([]))
        result = runner.tick()
        assert result.ran is False
        assert "closed" in result.reason

    def test_extended_hours_rth_only_manages_positions_only(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 5, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                         executor=executor)
        result = runner.tick()
        assert "rth_only" in result.reason
        assert result.entries_submitted == []
        assert executor.calls == []  # no new entries in pre-market


class TestEntries:
    def test_rth_entry_submitted(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                         executor=executor)
        result = runner.tick()
        assert result.proposals >= 1
        assert len(executor.calls) == 1
        call = executor.calls[0]
        assert call["symbol"] == "AAPL"
        assert call["side"] == "buy"
        assert call["role"] == "entry"
        assert "AAPL" in runner._state["entries_submitted"]

    def test_entry_not_resubmitted_same_day(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                         executor=executor)
        runner.tick()
        runner.tick()
        assert len(executor.calls) == 1  # idempotent: only one entry


class TestKillSwitch:
    def test_kill_switch_blocks_new_entries(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                         executor=executor, reconciler=FakeReconciler(kill=True))
        runner.risk.engage_kill_switch("DAILY_LOSS_BREACHED")
        result = runner.tick()
        assert result.kill_switch_active is True
        assert executor.calls == []


class TestExits:
    def test_stop_exit_submitted(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock,
                         market_data=FakeMarketData([{"symbol": "AAPL", "price": 95.0}]),
                         executor=executor)
        # Seed an open position whose stop (99.0) is breached at price 95.0.
        runner._state["positions_meta"] = {
            "AAPL": {"entry_price": 100.0, "stop_price": 99.0, "target_price": 105.0,
                     "quantity": 10, "breakeven_moved": False, "partial_taken": False},
        }
        result = runner.tick()
        assert len(result.exits_submitted) == 1
        assert result.exits_submitted[0]["symbol"] == "AAPL"
        assert "AAPL" not in runner._state["positions_meta"]

    def test_flatten_at_flatten_time(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 15, 50, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock,
                         market_data=FakeMarketData([{"symbol": "AAPL", "price": 101.0}]),
                         executor=executor)
        runner._state["positions_meta"] = {
            "AAPL": {"entry_price": 100.0, "stop_price": 99.0, "target_price": 105.0,
                     "quantity": 10, "breakeven_moved": False, "partial_taken": False},
        }
        result = runner.tick()
        assert "flatten" in result.reason
        assert len(result.exits_submitted) == 1
        assert runner._state["flattened"] is True


class TestCrashRecovery:
    def test_state_persists_and_reloads(self):
        clock = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        executor = FakeExecutor()
        runner = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                         executor=executor)
        runner.tick()
        assert "AAPL" in runner._state["entries_submitted"]

        # Simulate a restart: a fresh runner reloads persisted per-day state.
        runner2 = _runner(_cfg(), clock=clock, market_data=FakeMarketData([_entry_snapshot()]),
                          executor=FakeExecutor())
        assert "AAPL" in runner2._state["entries_submitted"]
        # No duplicate entry after restart.
        result = runner2.tick()
        assert result.entries_submitted == [] or all(
            c["symbol"] != "AAPL" for c in runner2.executor.calls
        )
