"""Autonomous trading loop — the wall-clock equivalent of the strategy iteration.

``AutonomousRunner.tick()`` is the production analogue of
``StocksInPlayOrbV1._iteration()``: it runs once per scheduler tick on real ET wall-clock
time and drives the same :class:`OrbEngine` signal/exit logic the backtest uses, but routes
orders through the Alpaca order workflow with session-aware order types.

Design notes
------------
* ONE time source: :class:`SessionClock` (ET). No ``datetime.utcnow()`` for trading logic.
* RTH-only signals by default: opening-range / RVOL / VWAP / spread are RTH constructs.
  Outside RTH the runner only *manages existing positions* (extended-hours-compatible
  marketable-limit exits). It never fabricates bars to manufacture an extended-hours signal.
* Crash recovery: per-symbol engine state + position metadata persist to ``orb_runtime_state``
  keyed by the ET session day, and reload on construction so a restart does not duplicate
  entries or re-arm proposals.
* Kill switch: if the risk engine kill switch is active, no new entries are submitted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.database import (
    get_orb_runtime_state,
    get_watchlist,
    insert_log,
    set_orb_runtime_state,
)
from backend.services.fill_reconciler import FillReconciler
from backend.services.market_data import MarketDataService
from backend.services.order_execution import OrderExecutionService
from backend.services.position_manager import PositionManager
from lumibot.custom_config.risk_engine import RiskEngine
from lumibot.custom_strategies.orb_engine import ExitReason, OrbEngine
from lumibot.custom_strategies.orb_runtime import OrbSimulationService
from lumibot.custom_strategies.session import (
    EXTENDED_SESSIONS,
    Session,
    SessionClock,
    SessionWindows,
)
from lumibot.custom_strategies.stocks_in_play_orb_v1 import STRATEGY_ID

logger = logging.getLogger(__name__)


@dataclass
class TickResult:
    session: str
    session_day: str
    ran: bool = True
    reason: str = ""
    entries_submitted: list[dict] = field(default_factory=list)
    exits_submitted: list[dict] = field(default_factory=list)
    proposals: int = 0
    candidates_count: int = 0
    kill_switch_active: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


class AutonomousRunner:
    def __init__(self, cfg: dict, *, market_data=None, executor=None, reconciler=None,
                 risk: RiskEngine | None = None, clock: SessionClock | None = None,
                 equity_provider=None, position_manager=None):
        self.cfg = cfg
        self._orb_cfg = {**cfg.get("stocks_in_play_orb_v1", {})}
        self.clock = clock or SessionClock(SessionWindows.from_config(self._orb_cfg))
        self.risk = risk or RiskEngine(cfg, clock=self.clock)
        self.market_data = market_data or MarketDataService(cfg)
        self.executor = executor or OrderExecutionService(cfg, risk=self.risk, clock=self.clock)
        self.reconciler = reconciler or FillReconciler(cfg, risk=self.risk)
        # Manages TP/SL exits for options & crypto positions (runs even when the stock market
        # is closed, since crypto trades 24/7).
        self.position_manager = position_manager or PositionManager(cfg)
        self._equity_provider = equity_provider or self._account_equity
        self._rth_only = str(self._orb_cfg.get("extended_hours_signals", "rth_only")).lower() == "rth_only"
        # Crash recovery: reload persisted per-day state.
        self._state = self._load_state()

    def _account_equity(self) -> float:
        """Real account equity from Alpaca (for position sizing). 0.0 if unavailable."""
        try:
            from backend.services.exposure_service import ExposureService

            snap = ExposureService(self.cfg).snapshot()
            return float(snap.get("account_equity") or snap.get("capital_limit") or 0.0)
        except Exception:
            return 0.0

    # ── state persistence ────────────────────────────────────────────────
    def _load_state(self) -> dict:
        rt = get_orb_runtime_state(STRATEGY_ID, self.clock.session_day_str())
        if rt and rt.get("state"):
            return rt["state"]
        return {
            "session_day": self.clock.session_day_str(),
            "or_captured": False,
            "ranked": False,
            "candidates": [],
            "entries_submitted": [],   # symbols with an entry already submitted today
            "positions_meta": {},       # symbol -> {entry_price, stop_price, target_price, quantity, ...}
            "flattened": False,
        }

    def _save_state(self) -> None:
        set_orb_runtime_state(STRATEGY_ID, self._state, self.clock.session_day_str())

    def _roll_day_if_needed(self) -> None:
        today = self.clock.session_day_str()
        if self._state.get("session_day") != today:
            logger.info("Session day rolled %s -> %s; resetting runner state",
                        self._state.get("session_day"), today)
            self._state = {
                "session_day": today,
                "or_captured": False,
                "ranked": False,
                "candidates": [],
                "entries_submitted": [],
                "positions_meta": {},
                "flattened": False,
            }

    # ── main tick ──────────────────────────────────────────────────────
    def tick(self) -> TickResult:
        self._roll_day_if_needed()
        session = self.clock.session()
        result = TickResult(session=session, session_day=self.clock.session_day_str())

        # Always reconcile fills first so realized PnL / kill switch are current. This runs even
        # when the stock market is closed because options/crypto orders may still be filling and
        # crypto trades 24/7.
        try:
            recon = self.reconciler.reconcile()
            result.kill_switch_active = bool(recon.get("kill_switch_active"))
        except Exception as exc:  # never let reconciliation crash the loop
            result.warnings.append(f"reconcile failed: {exc}")

        # Managed TP/SL exits for options & crypto positions run on every tick (crypto 24/7).
        try:
            managed = self.position_manager.manage()
            if managed.exits:
                result.exits_submitted.extend(managed.exits)
            result.warnings.extend(managed.warnings)
        except Exception as exc:
            result.warnings.append(f"position manager failed: {exc}")

        if session == Session.CLOSED:
            result.ran = False
            result.reason = "market closed (managed exits only)"
            return result

        now_t = self.clock.now().time()
        # Forced flatten at/after flatten_time (works across all sessions).
        flatten_t = _t(self._orb_cfg.get("flatten_time", "15:45"))
        if now_t >= flatten_t and not self._state.get("flattened"):
            self._flatten_all(result, session)
            self._state["flattened"] = True
            self._save_state()
            result.reason = "flatten_time reached"
            return result

        # Manage exits on every tradeable tick (extended-hours-compatible types).
        self._manage_exits(result, session)

        # New entries only in RTH (rth_only) and only when the kill switch is clear.
        in_extended = session in EXTENDED_SESSIONS
        if self.risk.kill_switch_active:
            result.kill_switch_active = True
            result.reason = "kill switch active; no new entries"
        elif in_extended and self._rth_only:
            result.reason = "extended hours: managing positions only (rth_only signals)"
        elif session == Session.REGULAR or (in_extended and not self._rth_only):
            self._evaluate_entries(result, session)

        self._save_state()
        return result

    # ── entries ────────────────────────────────────────────────────────
    def _evaluate_entries(self, result: TickResult, session: str) -> None:
        symbols = [s.upper() for s in get_watchlist("stocks")] or \
                  [s.upper() for s in self.cfg.get("watchlist", {}).get("stocks", [])]
        if not symbols:
            return
        md = self.market_data.snapshots(symbols, extended_hours=session in EXTENDED_SESSIONS)
        result.warnings.extend(md.warnings)
        if not md.snapshots:
            return  # honest: no data => no entries (gaps stay gaps)

        service = OrbSimulationService(self._orb_cfg)
        equity = float(self._equity_provider() or 0.0)
        evaluation = service.evaluate_snapshots(
            md.snapshots,
            regime_state=self.cfg.get("regime_state", "unknown"),
            equity=equity,
            now_time=self.clock.now().time(),
            is_live=self.cfg.get("trading_mode") == "live",
        )
        result.candidates_count = len(evaluation.get("candidates", []))
        self._state["candidates"] = evaluation.get("candidates", [])
        pending = [p for p in evaluation.get("proposals", []) if p.get("status") == "pending"]
        result.proposals = len(pending)

        snap_by_symbol = {s["symbol"].upper(): s for s in md.snapshots}
        for proposal in pending:
            sym = proposal["symbol"].upper()
            if sym in self._state["entries_submitted"]:
                continue
            qty = int(proposal.get("quantity") or 0)
            if qty <= 0:
                continue
            ref = snap_by_symbol.get(sym, {}).get("price") or proposal.get("proposed_entry")
            exec_res = self.executor.submit_intent(
                symbol=sym, side="buy", quantity=qty, intent="stop",
                reference_price=ref, stop_price=proposal.get("proposed_entry"),
                role="entry", strategy_id=STRATEGY_ID,
            )
            result.entries_submitted.append({"symbol": sym, **exec_res.to_dict()})
            if exec_res.status not in {"failed", "risk_rejected", "blocked", "skipped"}:
                self._state["entries_submitted"].append(sym)
                self._state["positions_meta"][sym] = {
                    "entry_price": proposal.get("proposed_entry"),
                    "stop_price": proposal.get("stop_price"),
                    "target_price": proposal.get("target_price"),
                    "quantity": qty,
                    "breakeven_moved": False,
                    "partial_taken": False,
                }

    # ── exits ──────────────────────────────────────────────────────────
    def _manage_exits(self, result: TickResult, session: str) -> None:
        metas = self._state.get("positions_meta", {})
        if not metas:
            return
        symbols = list(metas.keys())
        md = self.market_data.snapshots(symbols, extended_hours=session in EXTENDED_SESSIONS)
        result.warnings.extend(md.warnings)
        price_by_symbol = {s["symbol"].upper(): s.get("price") for s in md.snapshots}
        engine = OrbEngine(self._orb_cfg)
        engine.kill_switch_active = self.risk.kill_switch_active
        now_t = self.clock.now().time()

        for sym, meta in list(metas.items()):
            price = price_by_symbol.get(sym)
            if price is None:
                # No real price this tick — do not act on a fabricated value.
                continue
            ctx = {"price": float(price), "now_time": now_t, "vwap": None, "bar_closed": True}
            action = engine.evaluate_exit(sym, meta, ctx)
            if not action:
                continue
            act = action["action"]
            if act in ("exit_all", "exit_remainder"):
                self._submit_exit(result, sym, meta, action.get("reason", ExitReason.STOP), price,
                                  meta.get("quantity", 0), role=f"exit-{action.get('reason','exit')}".lower())
                metas.pop(sym, None)
            elif act == "take_partial":
                half = max(1, int(meta.get("quantity", 0) // 2))
                self._submit_exit(result, sym, meta, ExitReason.TARGET, price, half, role="partial")
                meta["partial_taken"] = True
                meta["quantity"] = meta.get("quantity", 0) - half
            elif act == "move_stop_breakeven":
                meta["breakeven_moved"] = True
                meta["stop_price"] = meta.get("entry_price")

    def _submit_exit(self, result: TickResult, symbol: str, meta: dict, reason: str,
                     price: float, qty: int, *, role: str) -> None:
        if qty <= 0:
            return
        exec_res = self.executor.submit_intent(
            symbol=symbol, side="sell", quantity=qty, intent="market",
            reference_price=price, role=role, strategy_id=STRATEGY_ID,
            seq=self._state.setdefault("exit_seq", {}).get(symbol, 0),
        )
        # bump per-symbol exit sequence so repeated exits get unique idempotency keys
        self._state.setdefault("exit_seq", {})[symbol] = \
            self._state.setdefault("exit_seq", {}).get(symbol, 0) + 1
        result.exits_submitted.append({"symbol": symbol, "reason": reason, **exec_res.to_dict()})

    def _flatten_all(self, result: TickResult, session: str) -> None:
        metas = self._state.get("positions_meta", {})
        if not metas:
            return
        symbols = list(metas.keys())
        md = self.market_data.snapshots(symbols, extended_hours=session in EXTENDED_SESSIONS)
        price_by_symbol = {s["symbol"].upper(): s.get("price") for s in md.snapshots}
        for sym, meta in list(metas.items()):
            price = price_by_symbol.get(sym) or meta.get("entry_price")
            if price is None:
                result.warnings.append(f"{sym}: cannot flatten without a real price")
                continue
            self._submit_exit(result, sym, meta, ExitReason.TIME_EXIT, price,
                              meta.get("quantity", 0), role="flatten")
            metas.pop(sym, None)
        insert_log("strategy", "Autonomous flatten executed (flatten_time)",
                   strategy=STRATEGY_ID, details={"symbols": symbols})


def _t(value):
    from datetime import datetime, time

    if isinstance(value, time):
        return value
    return datetime.strptime(str(value), "%H:%M").time()
