"""Signal engine for the Stocks In Play ORB v1 strategy.

This module is deliberately framework-agnostic: it contains no Lumibot or
FastAPI imports so it can be unit tested in isolation and reused across
backtest, simulation, and autonomous (proposal) modes through the same logic.

Design: proposal-first. The engine evaluates signals and emits ``Proposal``
objects. It never places live broker orders. Live placement happens through the
Alpaca order workflow after risk approval.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Sequence

from lumibot.custom_strategies import indicators

# ── Configurable defaults (mirrored in defaults.yaml + strategy template) ──

ORB_DEFAULTS: dict[str, Any] = {
    # Session / timing (US/Eastern)
    "opening_range_start": "09:30",
    "opening_range_end": "09:35",
    "entry_window_start": "09:35",
    "entry_window_end": "10:30",
    "flatten_time": "15:45",
    "max_entries_per_symbol_per_day": 1,
    # Universe filters
    "min_price": 5.0,
    "max_price": 500.0,
    "min_avg_daily_dollar_volume": 50_000_000.0,
    "min_avg_share_volume_20d": 500_000.0,
    "min_daily_atr_14": 0.50,
    "rvol_min": 2.0,
    "top_candidates": 10,
    "allowed_asset_class": "stocks",
    # Long trigger
    "breakout_buffer": 0.0,  # absolute $; if 0, one tick is used
    "tick_size": 0.01,
    "require_above_vwap": True,
    # Spread filter
    "spread_cap_abs": 0.05,
    "spread_cap_bps": 10.0,
    # Market regime filter
    "enable_spy_regime_filter": True,
    "spy_daily_ema_period": 200,
    "allow_if_spy_above_daily_ema_200": True,
    "enable_intraday_spy_vwap_filter": False,
    # Stop / target / sizing
    "atr_stop_factor": 0.15,
    "risk_per_trade_pct": 0.25,
    "max_position_notional_pct": 10.0,
    "max_portfolio_gross_pct": 50.0,
    "max_volume_participation_pct": 5.0,
    # Exits
    "partial_at_R": 2.0,
    "move_stop_to_breakeven_after_R": 1.5,
    "exit_on_vwap_loss": True,
    # Daily controls
    "max_daily_loss_pct": 1.0,
    "max_trades_per_day": 3,
    "max_consecutive_losses": 3,
    # Data freshness / slippage
    "max_quote_age_seconds": 60,
    "max_bar_age_seconds": 300,
    "max_slippage_buffer_pct": 0.5,
}


class ExitReason:
    STOP = "STOP"
    TARGET = "TARGET"
    TIME_EXIT = "TIME_EXIT"
    VWAP_LOST = "VWAP_LOST"
    REGIME_OFF = "REGIME_OFF"
    KILL_SWITCH = "KILL_SWITCH"
    MANUAL_FLATTEN = "MANUAL_FLATTEN"


class KillSwitchReason:
    DAILY_LOSS = "DAILY_LOSS_BREACHED"
    STALE_QUOTE = "STALE_QUOTE"
    STALE_BAR = "STALE_BAR"
    ORDER_REJECTIONS = "REPEATED_ORDER_REJECTION"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    MISSING_ACCOUNT = "MISSING_ACCOUNT_STATE"
    STRATEGY_EXCEPTION = "STRATEGY_EXCEPTION"
    SPREAD_EXCEEDED = "SPREAD_EXCEEDED_AFTER_PROPOSAL"
    SLIPPAGE = "SLIPPAGE_BUFFER_EXCEEDED"
    OUT_OF_SESSION = "OUT_OF_SESSION"


class ProposalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


# ── Proposal schema (#11) ──────────────────────────────────────────────────

@dataclass
class Proposal:
    strategy_id: str
    strategy_name: str
    symbol: str
    side: str = "buy"
    setup_name: str = "opening_range_breakout_long"
    timestamp: str | None = None
    entry_type: str = "stop"
    proposed_entry: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    expected_R: float | None = None
    quantity: float | None = None
    risk_dollars: float | None = None
    risk_pct: float | None = None
    spread: float | None = None
    spread_check_status: str = "unknown"
    rvol: float | None = None
    atr_14: float | None = None
    vwap: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    opening_range_open: float | None = None
    opening_range_close: float | None = None
    regime_state: str = "unknown"
    invalidation_reason: str | None = None
    status: str = ProposalStatus.PENDING
    is_simulation: bool = True
    is_live: bool = False
    data_quality_flags: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Per-symbol strategy state (#12) ─────────────────────────────────────────

@dataclass
class SymbolState:
    symbol: str
    opening_range_captured: bool = False
    candidate_rank: int | None = None
    breakout_pending: bool = False
    proposal_generated: bool = False
    proposal_status: str | None = None
    order_accepted: bool = False
    order_rejected: bool = False
    partial_filled: bool = False
    flat: bool = True
    closed: bool = False
    lockout_for_day: bool = False
    last_rejection_reason: str | None = None
    entries_today: int = 0
    opening_range: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    return datetime.strptime(value, "%H:%M").time()


def in_window(now: time, start: str | time, end: str | time) -> bool:
    """Inclusive-start, exclusive-end window check on a clock ``time``."""
    s, e = _parse_time(start), _parse_time(end)
    return s <= now < e


class OrbEngine:
    """Stateful per-trading-day ORB signal evaluator."""

    def __init__(self, config: dict | None = None, *, strategy_id: str = "stocks_in_play_orb_v1",
                 strategy_name: str = "Stocks In Play ORB v1"):
        self.config = {**ORB_DEFAULTS, **(config or {})}
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.states: dict[str, SymbolState] = {}
        self.candidates: list[str] = []
        self.consecutive_losses = 0
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.rejection_count = 0
        self.kill_switch_active = False
        self.kill_switch_reasons: list[str] = []

    # -- config accessors --
    def cfg(self, key: str):
        return self.config.get(key, ORB_DEFAULTS.get(key))

    def state(self, symbol: str) -> SymbolState:
        symbol = symbol.upper()
        if symbol not in self.states:
            self.states[symbol] = SymbolState(symbol=symbol)
        return self.states[symbol]

    def reset_day(self) -> None:
        self.states = {}
        self.candidates = []
        self.consecutive_losses = 0
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.rejection_count = 0
        self.kill_switch_active = False
        self.kill_switch_reasons = []

    # ── Universe filters (#2) ────────────────────────────────────────────
    def passes_universe_filters(self, metrics: dict) -> tuple[bool, str]:
        price = metrics.get("price")
        if price is None:
            return False, "price unavailable"
        if price < self.cfg("min_price"):
            return False, f"price {price} < min_price {self.cfg('min_price')}"
        if price > self.cfg("max_price"):
            return False, f"price {price} > max_price {self.cfg('max_price')}"

        addv = metrics.get("avg_daily_dollar_volume")
        if addv is not None and addv < self.cfg("min_avg_daily_dollar_volume"):
            return False, "avg daily dollar volume below minimum"

        avg_vol = metrics.get("avg_share_volume_20d")
        if avg_vol is not None and avg_vol < self.cfg("min_avg_share_volume_20d"):
            return False, "avg share volume below minimum"

        atr14 = metrics.get("atr_14")
        if atr14 is not None and atr14 < self.cfg("min_daily_atr_14"):
            return False, "daily ATR14 below minimum"

        return True, "ok"

    # ── Opening range capture (#3) ──────────────────────────────────────
    def capture_opening_range(self, symbol: str, or_bars: Sequence[dict]) -> dict | None:
        st = self.state(symbol)
        or_data = indicators.opening_range(or_bars)
        if or_data is None:
            return None
        st.opening_range = or_data
        st.opening_range_captured = True
        return or_data

    def rank_candidates(self, symbol_rvols: dict[str, float | None]) -> list[str]:
        """Rank symbols by RVOL desc, keep those meeting rvol_min, top N.

        Requires a green opening-range candle to qualify for long setups.
        """
        rvol_min = self.cfg("rvol_min")
        eligible: list[tuple[str, float]] = []
        for symbol, rv in symbol_rvols.items():
            st = self.state(symbol)
            if rv is None or rv < rvol_min:
                continue
            if not st.opening_range or not st.opening_range.get("is_green"):
                continue
            eligible.append((symbol.upper(), rv))
        eligible.sort(key=lambda x: x[1], reverse=True)
        top_n = int(self.cfg("top_candidates"))
        ranked = [s for s, _ in eligible[:top_n]]
        self.candidates = ranked
        for rank, sym in enumerate(ranked, start=1):
            self.state(sym).candidate_rank = rank
        return ranked

    # ── Kill-switch (#10) ────────────────────────────────────────────────
    def check_kill_switch(self, context: dict) -> list[str]:
        reasons: list[str] = []
        equity = context.get("equity")
        max_daily_loss_pct = self.cfg("max_daily_loss_pct")
        if equity and equity > 0:
            loss_pct = (-self.daily_pnl / equity) * 100.0 if self.daily_pnl < 0 else 0.0
            if loss_pct >= max_daily_loss_pct:
                reasons.append(KillSwitchReason.DAILY_LOSS)

        if context.get("quote_age_seconds") is not None and \
                context["quote_age_seconds"] > self.cfg("max_quote_age_seconds"):
            reasons.append(KillSwitchReason.STALE_QUOTE)
        if context.get("bar_age_seconds") is not None and \
                context["bar_age_seconds"] > self.cfg("max_bar_age_seconds"):
            reasons.append(KillSwitchReason.STALE_BAR)
        if self.rejection_count >= 3:
            reasons.append(KillSwitchReason.ORDER_REJECTIONS)
        if context.get("position_mismatch"):
            reasons.append(KillSwitchReason.POSITION_MISMATCH)
        if context.get("missing_account_state") and context.get("is_live"):
            reasons.append(KillSwitchReason.MISSING_ACCOUNT)
        if context.get("strategy_exception"):
            reasons.append(KillSwitchReason.STRATEGY_EXCEPTION)
        now = context.get("now_time")
        if now is not None and not self._in_session(now):
            reasons.append(KillSwitchReason.OUT_OF_SESSION)

        if reasons:
            self.kill_switch_active = True
            for r in reasons:
                if r not in self.kill_switch_reasons:
                    self.kill_switch_reasons.append(r)
        return reasons

    def _in_session(self, now: time) -> bool:
        return in_window(now, self.cfg("opening_range_start"), self.cfg("flatten_time")) \
            or now == _parse_time(self.cfg("flatten_time"))

    # ── Stop / target / sizing (#7) ─────────────────────────────────────
    def compute_stop(self, entry_price: float, or_low: float | None, atr_14: float | None) -> float | None:
        tick = self.cfg("tick_size")
        candidates: list[float] = []
        if or_low is not None:
            candidates.append(or_low - tick)
        if atr_14 is not None:
            candidates.append(entry_price - atr_14 * self.cfg("atr_stop_factor"))
        if not candidates:
            return None
        # "lower of" the two stop candidates (further from entry, safer)
        return min(candidates)

    def size_position(self, entry_price: float, stop_price: float, equity: float,
                      avg_volume: float | None = None) -> dict:
        stop_distance = entry_price - stop_price
        if stop_distance <= 0:
            return {"quantity": 0, "stop_distance": stop_distance, "risk_dollars": 0.0}
        shares = indicators.fixed_fractional_shares(
            equity, self.cfg("risk_per_trade_pct"), stop_distance
        )
        shares = indicators.cap_shares_by_notional(
            shares, entry_price, equity, self.cfg("max_position_notional_pct")
        )
        if avg_volume is not None:
            shares = indicators.cap_shares_by_volume(
                shares, avg_volume, self.cfg("max_volume_participation_pct")
            )
        risk_dollars = shares * stop_distance
        return {
            "quantity": shares,
            "stop_distance": stop_distance,
            "risk_dollars": risk_dollars,
        }

    # ── Long trigger (#4) + spread (#5) + regime (#6) ───────────────────
    def evaluate_long(self, symbol: str, context: dict) -> Proposal | None:
        """Evaluate a long ORB breakout proposal for ``symbol``.

        ``context`` keys (all optional unless noted):
          price (required), bid, ask, vwap, atr_14, rvol, avg_volume,
          equity, regime_state ("risk_on"/"risk_off"/"unknown"), now_time,
          in_watchlist (bool), data_fresh (bool), quote_age_seconds,
          is_simulation, is_live.

        Returns a ``Proposal`` (status pending/rejected) or ``None`` when the
        symbol is not eligible to even produce a proposal record.
        """
        symbol = symbol.upper()
        st = self.state(symbol)
        cfg = self.config
        price = context.get("price")
        flags: list[str] = []

        if self.kill_switch_active:
            return self._rejected(symbol, context, "kill switch active", flags)

        # one entry / proposal per symbol per day + lockout
        if st.lockout_for_day or st.proposal_generated or \
                st.entries_today >= int(self.cfg("max_entries_per_symbol_per_day")):
            return None

        # daily trade cap
        if self.trades_today >= int(self.cfg("max_trades_per_day")):
            return self._rejected(symbol, context, "max trades per day reached", flags)
        if self.consecutive_losses >= int(self.cfg("max_consecutive_losses")):
            return self._rejected(symbol, context, "max consecutive losses reached", flags)

        # entry window
        now = context.get("now_time")
        if now is not None and not in_window(now, self.cfg("entry_window_start"), self.cfg("entry_window_end")):
            return None

        # must be in candidate set
        if symbol not in self.candidates:
            return None

        if not st.opening_range_captured or not st.opening_range:
            return None
        or_high = st.opening_range.get("high")
        or_low = st.opening_range.get("low")

        if price is None or or_high is None:
            return self._rejected(symbol, context, "missing price/opening range", flags)

        # breakout trigger
        buffer = self.cfg("breakout_buffer") or self.cfg("tick_size")
        trigger = or_high + buffer
        if price < trigger:
            st.breakout_pending = True
            return None

        # watchlist / universe membership
        if context.get("in_watchlist") is False:
            return self._rejected(symbol, context, "symbol not in approved watchlist/universe", flags)

        # data freshness
        if context.get("data_fresh") is False:
            flags.append("stale_data")
            return self._rejected(symbol, context, "quote/bar data not fresh", flags)

        # VWAP filter
        vwap = context.get("vwap")
        if self.cfg("require_above_vwap"):
            if vwap is None:
                flags.append("vwap_unavailable")
            elif price <= vwap:
                return self._rejected(symbol, context, "price not above VWAP", flags)

        # regime filter
        regime_state = context.get("regime_state", "unknown")
        if self.cfg("enable_spy_regime_filter"):
            if regime_state == "unknown":
                flags.append("regime_unavailable")  # blocks live, allows sim (handled by caller)
            elif regime_state != "risk_on" and self.cfg("allow_if_spy_above_daily_ema_200"):
                return self._rejected(symbol, context, "SPY regime risk-off", flags)

        # spread filter
        spread_res = indicators.spread_check(
            context.get("bid"), context.get("ask"),
            cap_abs=self.cfg("spread_cap_abs"), cap_bps=self.cfg("spread_cap_bps"),
            price=price,
        )
        spread_status = spread_res["status"]
        if spread_status == "degraded":
            flags.append("spread_degraded")
        elif spread_status == "fail":
            return self._rejected(symbol, context, spread_res["reason"], flags,
                                  spread=spread_res["spread_abs"], spread_status=spread_status)

        # stop / target / sizing
        atr_14 = context.get("atr_14")
        equity = context.get("equity") or 0.0
        stop = self.compute_stop(price, or_low, atr_14)
        if stop is None or stop >= price:
            return self._rejected(symbol, context, "invalid stop (no ATR / OR low)", flags,
                                  spread=spread_res.get("spread_abs"), spread_status=spread_status)

        sizing = self.size_position(price, stop, equity, context.get("avg_volume"))
        qty = sizing["quantity"]
        if qty <= 0:
            return self._rejected(symbol, context, "position size resolved to 0 shares", flags,
                                  spread=spread_res.get("spread_abs"), spread_status=spread_status)

        risk = price - stop
        target = price + self.cfg("partial_at_R") * risk
        expected_r = self.cfg("partial_at_R")

        is_live = bool(context.get("is_live", False))
        is_sim = bool(context.get("is_simulation", not is_live))

        # Degraded data blocks autonomous live placement but allows simulation.
        live_blockers = [f for f in flags if f in ("spread_degraded", "regime_unavailable", "vwap_unavailable")]
        if is_live and live_blockers:
            return self._rejected(
                symbol, context,
                f"degraded data blocks live placement: {', '.join(live_blockers)}",
                flags, spread=spread_res.get("spread_abs"), spread_status=spread_status,
            )

        st.proposal_generated = True
        st.proposal_status = ProposalStatus.PENDING
        st.breakout_pending = False

        proposal = Proposal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            symbol=symbol,
            side="buy",
            setup_name="opening_range_breakout_long",
            timestamp=context.get("timestamp") or _now_iso(),
            entry_type="stop",
            proposed_entry=round(price, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            expected_R=expected_r,
            quantity=qty,
            risk_dollars=round(sizing["risk_dollars"], 2),
            risk_pct=self.cfg("risk_per_trade_pct"),
            spread=spread_res.get("spread_abs"),
            spread_check_status=spread_status,
            rvol=context.get("rvol"),
            atr_14=atr_14,
            vwap=vwap,
            opening_range_high=or_high,
            opening_range_low=or_low,
            opening_range_open=st.opening_range.get("open"),
            opening_range_close=st.opening_range.get("close"),
            regime_state=regime_state,
            status=ProposalStatus.PENDING,
            is_simulation=is_sim,
            is_live=is_live,
            data_quality_flags=flags,
            diagnostics={
                "candidate_rank": st.candidate_rank,
                "breakout_trigger": trigger,
                "stop_distance": sizing["stop_distance"],
                "dollar_notional": round(qty * price, 2),
            },
        )
        return proposal

    def _rejected(self, symbol: str, context: dict, reason: str, flags: list[str],
                  *, spread: float | None = None, spread_status: str = "unknown") -> Proposal:
        st = self.state(symbol)
        st.last_rejection_reason = reason
        return Proposal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            symbol=symbol,
            timestamp=context.get("timestamp") or _now_iso(),
            proposed_entry=context.get("price"),
            rvol=context.get("rvol"),
            atr_14=context.get("atr_14"),
            vwap=context.get("vwap"),
            regime_state=context.get("regime_state", "unknown"),
            opening_range_high=(st.opening_range or {}).get("high"),
            opening_range_low=(st.opening_range or {}).get("low"),
            spread=spread,
            spread_check_status=spread_status,
            status=ProposalStatus.REJECTED,
            rejection_reason=reason,
            invalidation_reason=reason,
            is_live=bool(context.get("is_live", False)),
            is_simulation=bool(context.get("is_simulation", True)),
            data_quality_flags=flags,
        )

    # ── Exits (#8) ──────────────────────────────────────────────────────
    def evaluate_exit(self, symbol: str, position: dict, context: dict) -> dict | None:
        """Decide whether/how to exit an open long position.

        ``position`` keys: entry_price, stop_price, quantity, breakeven_moved,
        partial_taken. Returns an action dict or ``None`` to hold.
        """
        price = context.get("price")
        if price is None:
            return None
        entry = position.get("entry_price")
        stop = position.get("stop_price")
        now = context.get("now_time")
        vwap = context.get("vwap")

        if now is not None and (now >= _parse_time(self.cfg("flatten_time"))):
            return {"action": "exit_all", "reason": ExitReason.TIME_EXIT, "price": price}
        if self.kill_switch_active:
            return {"action": "exit_all", "reason": ExitReason.KILL_SWITCH, "price": price}
        if stop is not None and price <= stop:
            return {"action": "exit_all", "reason": ExitReason.STOP, "price": price}
        if self.cfg("exit_on_vwap_loss") and vwap is not None and \
                context.get("bar_closed") and price < vwap:
            return {"action": "exit_remainder", "reason": ExitReason.VWAP_LOST, "price": price}

        r = indicators.r_multiple(entry, stop, price)
        if r is not None:
            if not position.get("partial_taken") and r >= self.cfg("partial_at_R"):
                return {"action": "take_partial", "reason": ExitReason.TARGET, "price": price, "r": r}
            if not position.get("breakeven_moved") and r >= self.cfg("move_stop_to_breakeven_after_R"):
                return {"action": "move_stop_breakeven", "price": entry, "r": r}
        return None

    # ── Trade outcome bookkeeping ───────────────────────────────────────
    def record_trade_result(self, symbol: str, pnl: float) -> None:
        self.trades_today += 1
        self.daily_pnl += pnl
        st = self.state(symbol)
        st.entries_today += 1
        st.lockout_for_day = True
        st.closed = True
        st.flat = True
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def record_rejection(self, symbol: str, reason: str) -> None:
        self.rejection_count += 1
        st = self.state(symbol)
        st.order_rejected = True
        st.last_rejection_reason = reason

    # ── Trace stats (#20) ───────────────────────────────────────────────
    def trace_stats(self, *, portfolio_value: float | None = None, open_risk: float | None = None,
                    proposal_count: int = 0, reject_count: int = 0,
                    avg_spread: float | None = None, avg_rvol: float | None = None) -> dict:
        return {
            "portfolio_value": portfolio_value,
            "open_risk": open_risk,
            "daily_pnl": self.daily_pnl,
            "daily_trade_count": self.trades_today,
            "proposal_count": proposal_count,
            "reject_count": reject_count,
            "candidate_count": len(self.candidates),
            "avg_candidate_spread": avg_spread,
            "avg_candidate_rvol": avg_rvol,
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reasons": list(self.kill_switch_reasons),
        }


def _now_iso() -> str:
    # ET-localized to match the rest of the audit trail (one time source).
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).isoformat()
