"""Stocks In Play ORB v1 — a long-only opening-range-breakout Lumibot strategy.

Purpose: capture long opening-drive breakouts in liquid US stocks/ETFs after
the first 5-minute opening range (09:30-09:35 ET) is established.

This class is proposal-first. In BACKTEST mode it simulates fills so Lumibot can
produce performance analytics. In live/autonomous mode it must NOT place broker
orders directly. Proposals flow through the risk engine and Alpaca order
workflow. See ``docs/strategies/stocks_in_play_orb_v1.md``.
"""

from __future__ import annotations

import logging
from datetime import time
from zoneinfo import ZoneInfo

from lumibot.strategies.strategy import Strategy

from lumibot.custom_strategies import indicators, orb_runtime
from lumibot.custom_strategies.orb_engine import ORB_DEFAULTS, ExitReason, OrbEngine

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
STRATEGY_ID = "stocks_in_play_orb_v1"
STRATEGY_DISPLAY_NAME = "Stocks In Play ORB v1"


class StocksInPlayOrbV1(Strategy):
    """Long-only opening-range-breakout strategy (stocks/ETFs, regular hours)."""

    # Parameters are merged with ORB_DEFAULTS in initialize().
    parameters = {
        "symbols": [],
        "run_id": None,          # registry key for backtest result collection
        "mode": "backtest",      # backtest | simulation
        "regime_state": "risk_on",  # overridden by SPY computation when available
    }

    # ── lifecycle ───────────────────────────────────────────────────────
    def initialize(self):
        merged = {**ORB_DEFAULTS}
        for k, v in self.parameters.items():
            if k in ORB_DEFAULTS:
                merged[k] = v
        self._orb_cfg = merged
        self.engine = OrbEngine(merged, strategy_id=STRATEGY_ID, strategy_name=STRATEGY_DISPLAY_NAME)
        self.sleeptime = "1M"
        self.set_market("NYSE")
        self._symbols = [s.upper() for s in self.parameters.get("symbols", [])]
        self._run_id = self.parameters.get("run_id")
        self._or_captured_for_day = False
        self._candidates_ranked = False
        self._positions_meta: dict[str, dict] = {}
        self._proposal_count = 0
        self._reject_count = 0
        self._current_day = None

    def before_starting_trading(self):
        self.engine.reset_day()
        self._or_captured_for_day = False
        self._candidates_ranked = False
        self._positions_meta = {}

    def on_trading_iteration(self):
        try:
            self._iteration()
        except Exception as exc:  # never let a single iteration crash the run
            logger.exception("ORB iteration error: %s", exc)
            self.engine.kill_switch_active = True
            if self._run_id:
                orb_runtime.append(self._run_id, "data_quality_warnings", f"iteration error: {exc}")

    # ── core loop ─────────────────────────────────────────────────────────
    def _iteration(self):
        now_dt = self.get_datetime()
        try:
            et = now_dt.astimezone(_ET)
        except Exception:
            et = now_dt
        now_t = et.time()
        day = et.date()
        if day != self._current_day:
            self._current_day = day
            self.before_starting_trading()

        # 1) Capture opening ranges once the OR window has elapsed
        if not self._or_captured_for_day and now_t >= _t(self._orb_cfg["opening_range_end"]):
            self._capture_opening_ranges(et)
            self._or_captured_for_day = True

        # 2) Rank candidates by RVOL after OR capture
        if self._or_captured_for_day and not self._candidates_ranked:
            self._rank(et)
            self._candidates_ranked = True

        # 3) Forced flatten at/after flatten time
        if now_t >= _t(self._orb_cfg["flatten_time"]):
            self._flatten_all(ExitReason.TIME_EXIT)
            return

        # 4) Manage open positions
        self._manage_exits(now_t)

        # 5) Entry evaluation during the entry window
        if indicators_in_window(now_t, self._orb_cfg["entry_window_start"], self._orb_cfg["entry_window_end"]):
            self._evaluate_entries(et, now_t)

    def _session_minute_bars(self, symbol, et_now):
        """Return today's minute bars up to now, as list of bar dicts (ET)."""
        try:
            bars = self.get_historical_prices(symbol, 400, timestep="minute")
        except Exception:
            return []
        if bars is None or getattr(bars, "df", None) is None or bars.df.empty:
            return []
        out = []
        for idx, row in bars.df.iterrows():
            try:
                ts = idx.to_pydatetime().astimezone(_ET)
            except Exception:
                continue
            if ts.date() != et_now.date() or ts > et_now:
                continue
            out.append({
                "time": ts.time(),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
            })
        return out

    def _capture_opening_ranges(self, et_now):
        for symbol in self._symbols:
            bars = self._session_minute_bars(symbol, et_now)
            or_bars = [b for b in bars if indicators_in_window(
                b["time"], self._orb_cfg["opening_range_start"], self._orb_cfg["opening_range_end"])]
            if not or_bars:
                if self._run_id:
                    orb_runtime.append(self._run_id, "data_quality_warnings",
                                       f"{symbol}: no intraday opening-range bars (minute data unavailable)")
                continue
            self.engine.capture_opening_range(symbol, or_bars)

    def _rank(self, et_now):
        symbol_rvols = {}
        for symbol in self._symbols:
            st = self.engine.state(symbol)
            if not st.opening_range:
                symbol_rvols[symbol] = None
                continue
            or_vol = st.opening_range.get("volume")
            hist = self._historical_or_volume(symbol, et_now)
            symbol_rvols[symbol] = indicators.rvol(or_vol, hist) if hist else None
        ranked = self.engine.rank_candidates(symbol_rvols)
        if self._run_id:
            orb_runtime.append(self._run_id, "candidates", ranked)

    def _historical_or_volume(self, symbol, et_now):
        """Average first-5-minute volume over prior sessions (honest; empty if N/A)."""
        try:
            bars = self.get_historical_prices(symbol, 2000, timestep="minute")
        except Exception:
            return []
        if bars is None or getattr(bars, "df", None) is None or bars.df.empty:
            return []
        by_day: dict = {}
        for idx, row in bars.df.iterrows():
            try:
                ts = idx.to_pydatetime().astimezone(_ET)
            except Exception:
                continue
            if ts.date() >= et_now.date():
                continue
            if indicators_in_window(ts.time(), self._orb_cfg["opening_range_start"],
                                    self._orb_cfg["opening_range_end"]):
                by_day.setdefault(ts.date(), 0.0)
                by_day[ts.date()] += float(row.get("volume") or 0.0)
        return list(by_day.values())

    def _daily_atr(self, symbol):
        try:
            bars = self.get_historical_prices(symbol, 30, timestep="day")
        except Exception:
            return None
        if bars is None or getattr(bars, "df", None) is None or bars.df.empty:
            return None
        rows = [{"high": r.get("high"), "low": r.get("low"), "close": r.get("close")}
                for _, r in bars.df.iterrows()]
        return indicators.atr(rows, 14)

    def _evaluate_entries(self, et_now, now_t):
        equity = float(self.get_portfolio_value() or 0.0)
        for symbol in list(self.engine.candidates):
            st = self.engine.state(symbol)
            if st.lockout_for_day or st.proposal_generated:
                continue
            price = self.get_last_price(symbol)
            if not price or price <= 0:
                continue
            session_bars = self._session_minute_bars(symbol, et_now)
            vwap = indicators.vwap(session_bars)
            ctx = {
                "price": float(price),
                "vwap": vwap,
                "atr_14": self._daily_atr(symbol),
                "rvol": None,
                "avg_volume": None,
                "equity": equity,
                "regime_state": self.parameters.get("regime_state", "unknown"),
                "now_time": now_t,
                "in_watchlist": True,
                "data_fresh": True,
                "is_simulation": True,
                "is_live": False,
                "timestamp": et_now.isoformat(),
            }
            proposal = self.engine.evaluate_long(symbol, ctx)
            if proposal is None:
                continue
            if proposal.status == "rejected":
                self._reject_count += 1
                if self._run_id:
                    orb_runtime.append(self._run_id, "proposals", proposal.to_dict())
                continue
            self._proposal_count += 1
            if self._run_id:
                orb_runtime.append(self._run_id, "proposals", proposal.to_dict())
            # BACKTEST simulation: realize the entry so Lumibot can track PnL.
            self._simulate_entry(symbol, proposal)

    def _simulate_entry(self, symbol, proposal):
        qty = int(proposal.quantity or 0)
        if qty <= 0:
            return
        order = self.create_order(symbol, qty, "buy")
        self.submit_order(order)
        self._positions_meta[symbol] = {
            "entry_price": proposal.proposed_entry,
            "stop_price": proposal.stop_price,
            "target_price": proposal.target_price,
            "quantity": qty,
            "breakeven_moved": False,
            "partial_taken": False,
        }

    def _manage_exits(self, now_t):
        for symbol, meta in list(self._positions_meta.items()):
            pos = self.get_position(symbol)
            if pos is None or float(getattr(pos, "quantity", 0) or 0) == 0:
                self._positions_meta.pop(symbol, None)
                continue
            price = self.get_last_price(symbol)
            if not price:
                continue
            ctx = {"price": float(price), "now_time": now_t, "vwap": None, "bar_closed": True}
            action = self.engine.evaluate_exit(symbol, meta, ctx)
            if not action:
                continue
            act = action["action"]
            if act in ("exit_all", "exit_remainder"):
                self._close_position(symbol, action["reason"])
            elif act == "move_stop_breakeven":
                meta["breakeven_moved"] = True
                meta["stop_price"] = meta["entry_price"]
            elif act == "take_partial":
                meta["partial_taken"] = True
                half = max(1, int(meta["quantity"] // 2))
                self.submit_order(self.create_order(symbol, half, "sell"))

    def _close_position(self, symbol, reason):
        pos = self.get_position(symbol)
        if pos is None:
            self._positions_meta.pop(symbol, None)
            return
        qty = int(abs(float(getattr(pos, "quantity", 0) or 0)))
        if qty > 0:
            self.submit_order(self.create_order(symbol, qty, "sell"))
        meta = self._positions_meta.pop(symbol, None)
        if self._run_id and meta:
            price = self.get_last_price(symbol) or meta.get("entry_price")
            pnl = (float(price) - float(meta["entry_price"])) * meta["quantity"]
            self.engine.record_trade_result(symbol, pnl)
            orb_runtime.append(self._run_id, "trades", {
                "symbol": symbol,
                "entry_price": meta["entry_price"],
                "exit_price": price,
                "quantity": meta["quantity"],
                "pnl": pnl,
                "exit_reason": reason,
            })

    def _flatten_all(self, reason):
        for symbol in list(self._positions_meta.keys()):
            self._close_position(symbol, reason)

    def on_filled_order(self, position, order, price, quantity, multiplier):
        symbol = getattr(order.asset, "symbol", None)
        if symbol:
            st = self.engine.state(symbol)
            st.order_accepted = True
            st.flat = False

    def trace_stats(self, context, snapshot_before):
        stats = self.engine.trace_stats(
            portfolio_value=float(self.get_portfolio_value() or 0.0),
            proposal_count=self._proposal_count,
            reject_count=self._reject_count,
        )
        return stats


def _t(value) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


def indicators_in_window(now_t, start, end) -> bool:
    from lumibot.custom_strategies.orb_engine import in_window
    return in_window(now_t, start, end)
