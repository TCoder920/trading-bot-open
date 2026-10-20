"""Unit tests for ORB indicator helpers (no market-data providers)."""

import math

from lumibot.custom_strategies import indicators as ind


def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


class TestOpeningRange:
    def test_basic_range(self):
        bars = [_bar(10, 11, 9.5, 10.8), _bar(10.8, 11.5, 10.6, 11.2)]
        orr = ind.opening_range(bars)
        assert orr["high"] == 11.5
        assert orr["low"] == 9.5
        assert orr["open"] == 10
        assert orr["close"] == 11.2
        assert orr["is_green"] is True
        assert orr["bar_count"] == 2

    def test_red_candle(self):
        bars = [_bar(11, 11.2, 10.5, 10.6)]
        orr = ind.opening_range(bars)
        assert orr["is_green"] is False

    def test_empty_returns_none(self):
        assert ind.opening_range([]) is None
        assert ind.opening_range([{"open": None, "high": None, "low": None, "close": None}]) is None


class TestVWAP:
    def test_vwap_value(self):
        bars = [_bar(10, 10, 10, 10, 100), _bar(12, 12, 12, 12, 300)]
        # typical prices 10 and 12, weighted by 100 and 300 -> (10*100+12*300)/400 = 11.5
        assert ind.vwap(bars) == 11.5

    def test_zero_volume_returns_none(self):
        assert ind.vwap([_bar(10, 10, 10, 10, 0)]) is None


class TestATR:
    def test_atr_requires_enough_bars(self):
        bars = [_bar(10, 11, 9, 10) for _ in range(5)]
        assert ind.atr(bars, period=14) is None

    def test_atr_constant_range(self):
        # constant high-low of 2, no gaps -> ATR should converge to 2
        bars = [_bar(10, 11, 9, 10) for _ in range(20)]
        val = ind.atr(bars, period=14)
        assert val is not None
        assert math.isclose(val, 2.0, rel_tol=1e-6)


class TestRVOL:
    def test_rvol(self):
        assert ind.rvol(300, [100, 100, 100]) == 3.0

    def test_rvol_missing(self):
        assert ind.rvol(None, [100]) is None
        assert ind.rvol(100, []) is None


class TestEMA:
    def test_ema_constant(self):
        assert ind.ema([5] * 30, 10) == 5.0

    def test_ema_insufficient(self):
        assert ind.ema([1, 2], 10) is None


class TestSpread:
    def test_spread_abs_bps(self):
        assert round(ind.spread_abs(100.0, 100.1), 4) == 0.1
        bps = ind.spread_bps(100.0, 100.1)
        assert round(bps, 1) == 10.0

    def test_spread_check_pass(self):
        res = ind.spread_check(100.0, 100.02, cap_abs=0.05, cap_bps=10, price=100.0)
        assert res["status"] == "pass"

    def test_spread_check_fail(self):
        res = ind.spread_check(100.0, 100.20, cap_abs=0.05, cap_bps=10, price=100.0)
        assert res["status"] == "fail"

    def test_spread_check_degraded(self):
        res = ind.spread_check(None, None, cap_abs=0.05, cap_bps=10)
        assert res["status"] == "degraded"


class TestRMultipleAndSizing:
    def test_r_multiple_long(self):
        # entry 100, stop 98 -> risk 2; price 104 -> 2R
        assert ind.r_multiple(100, 98, 104) == 2.0

    def test_r_multiple_zero_risk(self):
        assert ind.r_multiple(100, 100, 104) is None

    def test_fixed_fractional_percent(self):
        # equity 100k, 0.25% risk = $250, stop distance $2 -> 125 shares
        assert ind.fixed_fractional_shares(100_000, 0.25, 2.0) == 125

    def test_fixed_fractional_zero_inputs(self):
        assert ind.fixed_fractional_shares(0, 0.25, 2.0) == 0
        assert ind.fixed_fractional_shares(100_000, 0.25, 0) == 0

    def test_cap_by_notional(self):
        # 125 shares * $100 = $12,500 notional; cap 10% of 100k = $10k -> 100 shares
        assert ind.cap_shares_by_notional(125, 100.0, 100_000, 10.0) == 100

    def test_cap_by_volume(self):
        # 5% of 10,000 avg volume = 500 shares cap
        assert ind.cap_shares_by_volume(1000, 10_000, 5.0) == 500
