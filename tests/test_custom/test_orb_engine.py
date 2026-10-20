"""Unit tests for the ORB signal engine (framework-agnostic)."""

from datetime import time

import pytest

from lumibot.custom_strategies.orb_engine import (
    ExitReason,
    KillSwitchReason,
    OrbEngine,
    Proposal,
    in_window,
)


def _green_or(high=100.0, low=98.0):
    return [
        {"open": 98.5, "high": (high + low) / 2, "low": low, "close": (high + low) / 2 + 0.2, "volume": 50000},
        {"open": (high + low) / 2, "high": high, "low": low + 0.1, "close": high - 0.1, "volume": 60000},
    ]


def _setup_candidate(engine, symbol="AAPL", rvol=3.0):
    engine.capture_opening_range(symbol, _green_or())
    engine.rank_candidates({symbol: rvol})


def _valid_ctx(**over):
    ctx = {
        "price": 101.0,
        "bid": 100.99,
        "ask": 101.01,
        "vwap": 100.0,
        "atr_14": 2.0,
        "rvol": 3.0,
        "avg_volume": 5_000_000,
        "equity": 100_000.0,
        "regime_state": "risk_on",
        "now_time": time(9, 40),
        "in_watchlist": True,
        "data_fresh": True,
        "is_simulation": True,
        "is_live": False,
    }
    ctx.update(over)
    return ctx


class TestWindow:
    def test_in_window_inclusive_start_exclusive_end(self):
        assert in_window(time(9, 35), "09:35", "10:30") is True
        assert in_window(time(10, 30), "09:35", "10:30") is False
        assert in_window(time(9, 34), "09:35", "10:30") is False


class TestOpeningRangeCapture:
    def test_capture_sets_state(self):
        e = OrbEngine()
        orr = e.capture_opening_range("AAPL", _green_or())
        assert orr is not None
        st = e.state("AAPL")
        assert st.opening_range_captured is True
        assert st.opening_range["high"] == 100.0

    def test_red_candle_not_ranked(self):
        e = OrbEngine()
        red = [{"open": 100, "high": 100.5, "low": 98, "close": 98.5, "volume": 1000}]
        e.capture_opening_range("AAPL", red)
        ranked = e.rank_candidates({"AAPL": 5.0})
        assert ranked == []  # red OR cannot be a long candidate


class TestRanking:
    def test_rvol_min_and_top_n(self):
        e = OrbEngine({"rvol_min": 2.0, "top_candidates": 2})
        for sym, rv in [("A", 5.0), ("B", 3.0), ("C", 1.5), ("D", 4.0)]:
            e.capture_opening_range(sym, _green_or())
        ranked = e.rank_candidates({"A": 5.0, "B": 3.0, "C": 1.5, "D": 4.0})
        assert ranked == ["A", "D"]  # C filtered (below min), top 2 by rvol


class TestLongTrigger:
    def test_valid_proposal(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx())
        assert p is not None
        assert p.status == "pending"
        assert p.side == "buy"
        assert p.quantity > 0
        assert p.stop_price < p.proposed_entry < p.target_price
        assert p.expected_R == 2.0

    def test_no_breakout_returns_none(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx(price=99.5))  # below OR high
        assert p is None
        assert e.state("AAPL").breakout_pending is True

    def test_below_vwap_rejected(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx(vwap=102.0))
        assert p.status == "rejected"
        assert "VWAP" in p.rejection_reason

    def test_not_in_candidates(self):
        e = OrbEngine()
        e.capture_opening_range("AAPL", _green_or())
        e.rank_candidates({"AAPL": 3.0})
        p = e.evaluate_long("MSFT", _valid_ctx())  # never captured/ranked
        assert p is None


class TestSpreadFilter:
    def test_wide_spread_rejected(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx(bid=100.5, ask=101.5))
        assert p.status == "rejected"
        assert "spread" in p.rejection_reason.lower()

    def test_degraded_spread_allows_simulation_blocks_live(self):
        e = OrbEngine()
        _setup_candidate(e)
        sim = e.evaluate_long("AAPL", _valid_ctx(bid=None, ask=None, is_live=False, is_simulation=True))
        assert sim.status == "pending"
        assert "spread_degraded" in sim.data_quality_flags

        e2 = OrbEngine()
        _setup_candidate(e2)
        live = e2.evaluate_long("AAPL", _valid_ctx(bid=None, ask=None, is_live=True, is_simulation=False))
        assert live.status == "rejected"
        assert "degraded data blocks live" in live.rejection_reason


class TestRegimeFilter:
    def test_risk_off_rejected(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx(regime_state="risk_off"))
        assert p.status == "rejected"
        assert "regime" in p.rejection_reason.lower()

    def test_unknown_regime_blocks_live(self):
        e = OrbEngine()
        _setup_candidate(e)
        live = e.evaluate_long("AAPL", _valid_ctx(regime_state="unknown", is_live=True, is_simulation=False))
        assert live.status == "rejected"


class TestSizingAndCaps:
    def test_fixed_fractional_sizing(self):
        e = OrbEngine()
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx())
        # risk 0.25% of 100k = $250; stop distance ~3.01 -> ~83 shares
        assert 80 <= p.quantity <= 85

    def test_notional_cap(self):
        # tiny equity forces notional cap to bite
        e = OrbEngine({"risk_per_trade_pct": 50, "max_position_notional_pct": 5})
        _setup_candidate(e)
        p = e.evaluate_long("AAPL", _valid_ctx(equity=10_000))
        # 5% of 10k = $500 max notional / $101 -> <= 4 shares
        assert p.quantity <= 5


class TestDailyControlsAndLockout:
    def test_one_trade_per_symbol_lockout(self):
        e = OrbEngine()
        _setup_candidate(e)
        e.record_trade_result("AAPL", pnl=-10)
        p = e.evaluate_long("AAPL", _valid_ctx())
        assert p is None  # locked out
        assert e.state("AAPL").lockout_for_day is True

    def test_entry_window_enforced(self):
        e = OrbEngine()
        _setup_candidate(e)
        early = e.evaluate_long("AAPL", _valid_ctx(now_time=time(9, 34)))
        assert early is None
        late = e.evaluate_long("AAPL", _valid_ctx(now_time=time(10, 31)))
        assert late is None

    def test_max_trades_per_day(self):
        e = OrbEngine({"max_trades_per_day": 1})
        _setup_candidate(e, "AAPL")
        _setup_candidate(e, "MSFT")
        e.trades_today = 1
        p = e.evaluate_long("AAPL", _valid_ctx())
        assert p.status == "rejected"
        assert "max trades" in p.rejection_reason

    def test_consecutive_losses(self):
        e = OrbEngine({"max_consecutive_losses": 2})
        _setup_candidate(e)
        e.consecutive_losses = 2
        p = e.evaluate_long("AAPL", _valid_ctx())
        assert p.status == "rejected"


class TestKillSwitch:
    def test_daily_loss_breach(self):
        e = OrbEngine({"max_daily_loss_pct": 1.0})
        e.daily_pnl = -1500  # 1.5% of 100k
        reasons = e.check_kill_switch({"equity": 100_000})
        assert KillSwitchReason.DAILY_LOSS in reasons
        assert e.kill_switch_active is True

    def test_stale_quote(self):
        e = OrbEngine()
        reasons = e.check_kill_switch({"equity": 100_000, "quote_age_seconds": 999})
        assert KillSwitchReason.STALE_QUOTE in reasons

    def test_out_of_session(self):
        e = OrbEngine()
        reasons = e.check_kill_switch({"equity": 100_000, "now_time": time(16, 30)})
        assert KillSwitchReason.OUT_OF_SESSION in reasons

    def test_kill_switch_blocks_proposals(self):
        e = OrbEngine()
        _setup_candidate(e)
        e.kill_switch_active = True
        p = e.evaluate_long("AAPL", _valid_ctx())
        assert p.status == "rejected"


class TestExits:
    def test_time_exit(self):
        e = OrbEngine()
        pos = {"entry_price": 100, "stop_price": 98, "quantity": 10}
        action = e.evaluate_exit("AAPL", pos, {"price": 101, "now_time": time(15, 45)})
        assert action["reason"] == ExitReason.TIME_EXIT

    def test_stop_exit(self):
        e = OrbEngine()
        pos = {"entry_price": 100, "stop_price": 98, "quantity": 10}
        action = e.evaluate_exit("AAPL", pos, {"price": 97.5, "now_time": time(10, 0)})
        assert action["reason"] == ExitReason.STOP

    def test_partial_at_2R(self):
        e = OrbEngine()
        pos = {"entry_price": 100, "stop_price": 98, "quantity": 10}
        action = e.evaluate_exit("AAPL", pos, {"price": 104, "now_time": time(10, 0)})
        assert action["action"] == "take_partial"

    def test_move_to_breakeven_at_1_5R(self):
        e = OrbEngine()
        pos = {"entry_price": 100, "stop_price": 98, "quantity": 10}
        action = e.evaluate_exit("AAPL", pos, {"price": 103, "now_time": time(10, 0)})
        assert action["action"] == "move_stop_breakeven"

    def test_vwap_loss_exit(self):
        e = OrbEngine()
        pos = {"entry_price": 100, "stop_price": 98, "quantity": 10}
        action = e.evaluate_exit("AAPL", pos, {"price": 99.5, "vwap": 100.2,
                                               "now_time": time(10, 0), "bar_closed": True})
        assert action["reason"] == ExitReason.VWAP_LOST


class TestProposalSchema:
    def test_proposal_has_all_required_fields(self):
        p = Proposal(strategy_id="stocks_in_play_orb_v1", strategy_name="Stocks In Play ORB v1", symbol="AAPL")
        d = p.to_dict()
        required = {
            "strategy_id", "strategy_name", "symbol", "side", "setup_name", "timestamp",
            "entry_type", "proposed_entry", "stop_price", "target_price", "expected_R",
            "quantity", "risk_dollars", "risk_pct", "spread", "spread_check_status", "rvol",
            "atr_14", "vwap", "opening_range_high", "opening_range_low", "opening_range_open",
            "opening_range_close", "regime_state", "invalidation_reason", "status",
            "is_simulation", "is_live", "data_quality_flags", "rejection_reason", "diagnostics",
        }
        assert required.issubset(set(d.keys()))


class TestTraceStats:
    def test_trace_stats_shape(self):
        e = OrbEngine()
        _setup_candidate(e)
        stats = e.trace_stats(portfolio_value=100_000, proposal_count=2, reject_count=1)
        for key in ("daily_pnl", "daily_trade_count", "proposal_count", "reject_count",
                    "candidate_count", "avg_candidate_spread", "avg_candidate_rvol"):
            assert key in stats
