"""Reusable, dependency-light indicator helpers for custom strategies.

Every helper operates on plain Python sequences of numbers or "bar" dicts with
``open``/``high``/``low``/``close``/``volume`` keys. They are intentionally pure
and deterministic so they can be unit tested without market-data providers.

NO-FABRICATION RULE: when there is not enough real input to compute a value,
these helpers return ``None`` (or an empty/identity result). They never invent
or carry-forward a value to keep a strategy alive.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


Bar = Mapping[str, float]


def _f(value) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Opening range ────────────────────────────────────────────────────────

def opening_range(bars: Sequence[Bar]) -> dict | None:
    """Compute the opening-range high/low/open/close from a list of bars.

    ``bars`` must already be filtered to the opening-range window (e.g. the
    first 5 minutes). Returns ``None`` when no usable bars are supplied.
    """
    valid = [b for b in bars if _f(b.get("high")) is not None and _f(b.get("low")) is not None]
    if not valid:
        return None

    highs = [_f(b.get("high")) for b in valid]
    lows = [_f(b.get("low")) for b in valid]
    or_open = _f(valid[0].get("open"))
    or_close = _f(valid[-1].get("close"))
    volume = sum((_f(b.get("volume")) or 0.0) for b in valid)

    or_high = max(highs)
    or_low = min(lows)

    return {
        "high": or_high,
        "low": or_low,
        "open": or_open,
        "close": or_close,
        "volume": volume,
        "is_green": (or_close is not None and or_open is not None and or_close > or_open),
        "bar_count": len(valid),
    }


# ── VWAP ───────────────────────────────────────────────────────────────────

def vwap(bars: Sequence[Bar]) -> float | None:
    """Volume-weighted average price using typical price (H+L+C)/3.

    Returns ``None`` if cumulative volume is zero or no usable bars exist.
    """
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        h, l, c = _f(b.get("high")), _f(b.get("low")), _f(b.get("close"))
        v = _f(b.get("volume"))
        if None in (h, l, c) or v is None or v <= 0:
            continue
        typical = (h + l + c) / 3.0
        cum_pv += typical * v
        cum_vol += v
    if cum_vol <= 0:
        return None
    return cum_pv / cum_vol


# ── ATR(14) ──────────────────────────────────────────────────────────────

def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """Per-bar true range series. Length is ``len(bars) - 1`` (needs prev close)."""
    trs: list[float] = []
    prev_close: float | None = None
    for b in bars:
        h, l, c = _f(b.get("high")), _f(b.get("low")), _f(b.get("close"))
        if None in (h, l, c):
            prev_close = c if c is not None else prev_close
            continue
        if prev_close is None:
            prev_close = c
            continue
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = c
    return trs


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    """Average True Range over ``period`` daily bars (Wilder smoothing).

    Requires at least ``period + 1`` usable bars. Returns ``None`` otherwise so
    callers can treat ATR as unavailable rather than fabricating a value.
    """
    trs = true_ranges(bars)
    if len(trs) < period:
        return None
    # Wilder's smoothing: seed with simple mean of first `period` TRs.
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


# ── RVOL ─────────────────────────────────────────────────────────────────

def rvol(current_volume, historical_volumes: Iterable[float]) -> float | None:
    """Relative volume = current volume / mean(historical volumes).

    Returns ``None`` when current volume or the historical average is
    unavailable / non-positive.
    """
    cur = _f(current_volume)
    if cur is None or cur < 0:
        return None
    hist = [v for v in (_f(x) for x in historical_volumes) if v is not None and v > 0]
    if not hist:
        return None
    avg = sum(hist) / len(hist)
    if avg <= 0:
        return None
    return cur / avg


# ── EMA ──────────────────────────────────────────────────────────────────

def ema(values: Sequence[float], period: int) -> float | None:
    """Exponential moving average; returns the most recent EMA value.

    Requires at least ``period`` usable values. Returns ``None`` otherwise.
    """
    vals = [v for v in (_f(x) for x in values) if v is not None]
    if period <= 0 or len(vals) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema_val = sum(vals[:period]) / period  # seed with SMA
    for v in vals[period:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


# ── Spread ───────────────────────────────────────────────────────────────

def spread_abs(bid, ask) -> float | None:
    b, a = _f(bid), _f(ask)
    if b is None or a is None or a <= 0 or b <= 0 or a < b:
        return None
    return a - b


def spread_bps(bid, ask, price: float | None = None) -> float | None:
    """Spread in basis points relative to the mid (or supplied price)."""
    b, a = _f(bid), _f(ask)
    if b is None or a is None or a <= 0 or b <= 0 or a < b:
        return None
    ref = _f(price) if price is not None else (a + b) / 2.0
    if ref is None or ref <= 0:
        return None
    return (a - b) / ref * 10_000.0


def spread_check(bid, ask, *, cap_abs: float, cap_bps: float, price: float | None = None) -> dict:
    """Evaluate the spread filter.

    Passes only when the absolute spread is <= the LOWER of ``cap_abs`` and
    ``cap_bps`` (expressed in dollars at the reference price).

    Returns a dict with ``status`` in {"pass", "fail", "degraded"} so callers
    can block live placement on degraded (missing quote) data while letting
    simulation continue.
    """
    sa = spread_abs(bid, ask)
    if sa is None:
        return {
            "status": "degraded",
            "reason": "bid/ask unavailable",
            "spread_abs": None,
            "spread_bps": None,
        }
    ref = _f(price) if price is not None else ((_f(ask) + _f(bid)) / 2.0)
    bps = spread_bps(bid, ask, price=ref)
    cap_from_bps = (cap_bps / 10_000.0) * ref if ref else float("inf")
    effective_cap = min(cap_abs, cap_from_bps)
    passes = sa <= effective_cap
    return {
        "status": "pass" if passes else "fail",
        "reason": "" if passes else f"spread {sa:.4f} exceeds cap {effective_cap:.4f}",
        "spread_abs": sa,
        "spread_bps": bps,
        "effective_cap": effective_cap,
    }


# ── R multiple & sizing ────────────────────────────────────────────────────

def r_multiple(entry, stop, price, side: str = "buy") -> float | None:
    """How many R the current price is from entry (long-only oriented).

    R = risk per share = abs(entry - stop). Returns ``None`` if risk is zero.
    """
    e, s, p = _f(entry), _f(stop), _f(price)
    if None in (e, s, p):
        return None
    risk = abs(e - s)
    if risk <= 0:
        return None
    if side == "sell":
        return (e - p) / risk
    return (p - e) / risk


def fixed_fractional_shares(
    equity, risk_pct, stop_distance, *, pct_is_percent: bool = True
) -> int:
    """Fixed-fractional position size.

    ``risk_pct`` is treated as a percent of equity by default (e.g. ``0.25`` =>
    0.25% of equity). Set ``pct_is_percent=False`` to treat it as a fraction.

    shares = floor((equity * risk_fraction) / stop_distance)
    Returns 0 when inputs are missing or non-positive (never negative).
    """
    eq, rp, sd = _f(equity), _f(risk_pct), _f(stop_distance)
    if None in (eq, rp, sd) or eq <= 0 or rp <= 0 or sd <= 0:
        return 0
    risk_fraction = rp / 100.0 if pct_is_percent else rp
    risk_dollars = eq * risk_fraction
    shares = math.floor(risk_dollars / sd)
    return max(0, int(shares))


def cap_shares_by_notional(shares: int, price: float, equity: float, max_notional_pct: float) -> int:
    """Cap share count so position notional <= max_notional_pct of equity."""
    p, eq = _f(price), _f(equity)
    if shares <= 0 or p is None or eq is None or p <= 0 or eq <= 0 or max_notional_pct <= 0:
        return max(0, shares)
    max_notional = eq * (max_notional_pct / 100.0)
    max_shares = math.floor(max_notional / p)
    return max(0, min(shares, int(max_shares)))


def cap_shares_by_volume(shares: int, avg_volume: float, max_participation_pct: float) -> int:
    """Cap share count to a max participation of average volume."""
    av = _f(avg_volume)
    if shares <= 0 or av is None or av <= 0 or max_participation_pct <= 0:
        return max(0, shares)
    max_shares = math.floor(av * (max_participation_pct / 100.0))
    return max(0, min(shares, int(max_shares)))
