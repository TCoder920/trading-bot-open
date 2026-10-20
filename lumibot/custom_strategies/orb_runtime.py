"""In-memory runtime registry + simulation service for the ORB strategy.

The registry lets a running Lumibot backtest hand proposals/trades back to the
caller without pickling problems. The simulation service runs the same
``OrbEngine`` over market-data snapshots supplied by the caller or Alpaca data
integrations to produce proposals in simulation/autonomous mode.
"""

from __future__ import annotations

import threading
from typing import Any

from lumibot.custom_strategies.orb_engine import OrbEngine

_LOCK = threading.Lock()
_REGISTRY: dict[str, dict[str, Any]] = {}


def new_run(run_id: str) -> dict:
    with _LOCK:
        _REGISTRY[run_id] = {
            "proposals": [],
            "trades": [],
            "candidates": [],
            "diagnostics": {},
            "data_quality_warnings": [],
        }
        return _REGISTRY[run_id]


def get_run(run_id: str) -> dict | None:
    with _LOCK:
        return _REGISTRY.get(run_id)


def append(run_id: str, key: str, value: Any) -> None:
    with _LOCK:
        run = _REGISTRY.get(run_id)
        if run is None:
            return
        if isinstance(run.get(key), list):
            run[key].append(value)
        else:
            run[key] = value


def pop_run(run_id: str) -> dict | None:
    with _LOCK:
        return _REGISTRY.pop(run_id, None)


class OrbSimulationService:
    """Evaluate ORB proposals from market-data snapshots (no live orders).

    Snapshot shape per symbol::

        {
          "symbol": "AAPL",
          "opening_range_bars": [ {open,high,low,close,volume}, ... ],
          "session_bars": [ ... ],   # bars so far today, for VWAP
          "price": 191.2, "bid": 191.18, "ask": 191.22,
          "atr_14": 2.1, "rvol": 3.4, "avg_volume": 60_000_000,
          "in_watchlist": True, "data_fresh": True,
        }

    The caller supplies ``regime_state`` and ``equity`` once for the batch.
    """

    def __init__(self, config: dict | None = None):
        self.engine = OrbEngine(config or {})

    def evaluate_snapshots(
        self,
        snapshots: list[dict],
        *,
        regime_state: str = "unknown",
        equity: float = 0.0,
        now_time=None,
        is_live: bool = False,
    ) -> dict:
        from lumibot.custom_strategies import indicators

        # 1) capture opening ranges + collect RVOL for ranking
        symbol_rvols: dict[str, float | None] = {}
        for snap in snapshots:
            sym = snap["symbol"].upper()
            or_bars = snap.get("opening_range_bars") or []
            self.engine.capture_opening_range(sym, or_bars)
            symbol_rvols[sym] = snap.get("rvol")
        self.engine.rank_candidates(symbol_rvols)

        proposals: list[dict] = []
        for snap in snapshots:
            sym = snap["symbol"].upper()
            session_bars = snap.get("session_bars") or []
            vwap = snap.get("vwap")
            if vwap is None and session_bars:
                vwap = indicators.vwap(session_bars)
            ctx = {
                "price": snap.get("price"),
                "bid": snap.get("bid"),
                "ask": snap.get("ask"),
                "vwap": vwap,
                "atr_14": snap.get("atr_14"),
                "rvol": snap.get("rvol"),
                "avg_volume": snap.get("avg_volume"),
                "equity": equity,
                "regime_state": regime_state,
                "now_time": now_time,
                "in_watchlist": snap.get("in_watchlist", True),
                "data_fresh": snap.get("data_fresh", True),
                "is_live": is_live,
                "is_simulation": not is_live,
            }
            proposal = self.engine.evaluate_long(sym, ctx)
            if proposal is not None:
                proposals.append(proposal.to_dict())

        return {
            "candidates": list(self.engine.candidates),
            "proposals": proposals,
            "states": {s: st.to_dict() for s, st in self.engine.states.items()},
            "trace_stats": self.engine.trace_stats(
                portfolio_value=equity,
                proposal_count=len([p for p in proposals if p["status"] == "pending"]),
                reject_count=len([p for p in proposals if p["status"] == "rejected"]),
            ),
        }
