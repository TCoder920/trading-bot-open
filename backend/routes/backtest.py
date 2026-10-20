"""Backtest routes."""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime

from fastapi import APIRouter, HTTPException

from backend.database import (
    get_backtest,
    get_backtests,
    get_strategy,
    insert_backtest,
    insert_log,
    insert_orb_proposal,
    update_backtest,
)
from backend.models import BacktestRequest
from backend import state
from backend.services.alpaca_service import AlpacaService

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

ORB_TEMPLATE = "stocks_in_play_orb_v1"


@router.get("")
def list_backtests(limit: int = 50):
    return {"backtests": get_backtests(limit=limit)}


@router.get("/{bt_id}")
def read_backtest(bt_id: int):
    bt = get_backtest(bt_id)
    if not bt:
        raise HTTPException(404, "Backtest not found")
    return bt


@router.post("")
def run_backtest(body: BacktestRequest):
    bt = insert_backtest(
        strategy_name=body.strategy_name,
        symbols=body.symbols,
        start_date=body.start_date,
        end_date=body.end_date,
        starting_cash=body.starting_cash,
        data_source=body.data_source,
    )
    insert_log("backtest", f"Backtest {bt['id']} queued: {body.strategy_name}",
               strategy=body.strategy_name)
    thread = threading.Thread(target=_run_backtest_worker, args=(bt["id"],), daemon=True)
    thread.start()
    return bt


def _resolve_template(bt: dict) -> tuple[str | None, dict]:
    """Return (template, strategy_config) for a backtest row."""
    strat = get_strategy(bt["strategy_name"])
    if strat:
        return strat.get("template"), strat.get("config", {})
    if bt["strategy_name"] == ORB_TEMPLATE:
        return ORB_TEMPLATE, {}
    return None, {}


def _run_backtest_worker(bt_id: int) -> None:
    """Run backtest in background thread using Lumibot's backtesting engine."""
    try:
        update_backtest(bt_id, status="running")
        bt = get_backtest(bt_id)
        if not bt:
            return

        template, strat_cfg = _resolve_template(bt)
        if template == ORB_TEMPLATE:
            _run_orb_backtest(bt_id, bt, strat_cfg)
            return

        from lumibot.strategies import Strategy

        class SimpleBacktestStrategy(Strategy):
            def initialize(self):
                self.sleeptime = "1D"
                self._bought = set()

            def on_trading_iteration(self):
                for symbol in self.parameters.get("symbols", []):
                    if symbol not in self._bought:
                        price = self.get_last_price(symbol)
                        if price and price > 0:
                            cash = self.get_cash()
                            dollar_amt = min(
                                self.parameters.get("dollar_amount", 1000),
                                cash * 0.95,
                            )
                            if dollar_amt > 0 and price > 0:
                                qty = int(dollar_amt / price)
                                if qty > 0:
                                    order = self.create_order(symbol, qty, "buy")
                                    self.submit_order(order)
                                    self._bought.add(symbol)

        start_dt = datetime.strptime(bt["start_date"], "%Y-%m-%d")
        end_dt = datetime.strptime(bt["end_date"], "%Y-%m-%d")
        datasource_class, datasource_config, warning = _resolve_backtesting_source(bt.get("data_source", "alpaca"))
        if warning:
            update_backtest(
                bt_id,
                status="completed",
                completed_at=datetime.utcnow().isoformat(),
                result_json=json.dumps({"data_quality_warnings": [warning], "metrics": {}}),
            )
            insert_log("backtest", f"Backtest {bt_id} skipped safely: {warning}", level="warning")
            return

        results = SimpleBacktestStrategy.backtest(
            datasource_class,
            start_dt,
            end_dt,
            config=datasource_config,
            timestep="day",
            budget=bt["starting_cash"],
            parameters={"symbols": bt["symbols"], "dollar_amount": bt["starting_cash"] / max(len(bt["symbols"]), 1)},
            show_plot=False,
            show_tearsheet=False,
            save_tearsheet=False,
            show_indicators=False,
            name=f"bt_{bt_id}",
        )

        result_summary = {}
        if results and isinstance(results, dict):
            result_summary = results
        elif results:
            result_summary = {"raw": str(results)[:2000]}

        update_backtest(
            bt_id,
            status="completed",
            completed_at=datetime.utcnow().isoformat(),
            result_json=json.dumps(result_summary),
        )
        insert_log("backtest", f"Backtest {bt_id} completed", details=result_summary)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
        update_backtest(bt_id, status="error", error=error_msg)
        insert_log("backtest", f"Backtest {bt_id} failed: {e}", level="error")


def _orb_metrics(trades: list[dict], proposals: list[dict], starting_cash: float) -> dict:
    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]
    total_pnl = sum((t.get("pnl") or 0) for t in trades)

    def _r(t):
        entry, exitp = t.get("entry_price"), t.get("exit_price")
        qty = t.get("quantity") or 0
        if not entry or not exitp or qty == 0:
            return None
        risk = abs(entry - (t.get("stop_price") or entry))
        return None if risk == 0 else (exitp - entry) / risk

    rs = [r for r in (_r(t) for t in trades) if r is not None]
    rvols = [p.get("rvol") for p in proposals if p.get("rvol") is not None]
    spreads = [p.get("spread") for p in proposals if p.get("spread") is not None]
    pnls = [t.get("pnl") or 0 for t in trades]

    def _avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    win_rate = round(len(wins) / len(trades) * 100, 2) if trades else None
    avg_win = _avg([t["pnl"] for t in wins]) or 0
    avg_loss = _avg([t["pnl"] for t in losses]) or 0
    expectancy = None
    if trades:
        wr = len(wins) / len(trades)
        expectancy = round(wr * avg_win + (1 - wr) * avg_loss, 4)

    return {
        "starting_cash": starting_cash,
        "ending_equity": round(starting_cash + total_pnl, 2),
        "total_return_pct": round(total_pnl / starting_cash * 100, 4) if starting_cash else None,
        "total_trades": len(trades),
        "win_rate_pct": win_rate,
        "average_R": _avg(rs),
        "expectancy": expectancy,
        "best_trade": round(max(pnls), 2) if pnls else None,
        "worst_trade": round(min(pnls), 2) if pnls else None,
        "rejected_signals": len([p for p in proposals if p.get("status") == "rejected"]),
        "proposals": len([p for p in proposals if p.get("status") == "pending"]),
        "average_rvol": _avg(rvols),
        "average_spread": _avg(spreads),
    }


def _run_orb_backtest(bt_id: int, bt: dict, strat_cfg: dict) -> None:
    """Run the Stocks In Play ORB v1 strategy through Lumibot.

    NO-FAKE-DATA: the 5-minute opening range requires minute bars. If Alpaca
    credentials are missing, the run records a data-quality warning rather than
    fabricating minute bars.
    """
    import uuid

    from lumibot.custom_strategies import orb_runtime
    from lumibot.custom_strategies.orb_engine import ORB_DEFAULTS
    from lumibot.custom_strategies.stocks_in_play_orb_v1 import StocksInPlayOrbV1

    run_id = f"bt_{bt_id}_{uuid.uuid4().hex[:8]}"
    orb_runtime.new_run(run_id)

    params = {k: v for k, v in ORB_DEFAULTS.items()}
    params.update({k: v for k, v in (strat_cfg or {}).items() if k in ORB_DEFAULTS})
    params.update({
        "symbols": bt["symbols"],
        "run_id": run_id,
        "mode": "backtest",
        "regime_state": "risk_on",
    })

    start_dt = datetime.strptime(bt["start_date"], "%Y-%m-%d")
    end_dt = datetime.strptime(bt["end_date"], "%Y-%m-%d")
    datasource_class, datasource_config, warning = _resolve_backtesting_source(bt.get("data_source", "alpaca"), timestep="minute")
    if warning:
        metrics = _orb_metrics([], [], bt["starting_cash"])
        warnings = [warning]
        result_summary = {
            "strategy": ORB_TEMPLATE,
            "metrics": metrics,
            "trades": [],
            "data_quality_warnings": warnings,
            "lumibot": {},
        }
        update_backtest(
            bt_id,
            status="completed",
            completed_at=datetime.utcnow().isoformat(),
            result_json=json.dumps(result_summary),
        )
        insert_log("backtest", f"ORB backtest {bt_id} skipped safely: {warning}", level="warning")
        return

    lumibot_results = {}
    try:
        lumibot_results = StocksInPlayOrbV1.backtest(
            datasource_class,
            start_dt,
            end_dt,
            config=datasource_config,
            timestep="minute",
            budget=bt["starting_cash"],
            parameters=params,
            show_plot=False,
            show_tearsheet=False,
            save_tearsheet=False,
            show_indicators=False,
            name=f"orb_bt_{bt_id}",
        ) or {}
    except Exception as e:  # honest failure surface; do not fabricate results
        insert_log("backtest", f"ORB backtest {bt_id} engine note: {e}", level="warning")

    run = orb_runtime.pop_run(run_id) or {}
    trades = run.get("trades", [])
    proposals = run.get("proposals", [])
    warnings = run.get("data_quality_warnings", [])

    for p in proposals:
        try:
            insert_orb_proposal(p, mode="backtest", run_id=run_id,
                                trade_date=bt["start_date"])
        except Exception:
            pass

    metrics = _orb_metrics(trades, proposals, bt["starting_cash"])
    if not trades and not proposals:
        warnings.append(
            "No intraday signals: the selected data source did not provide minute "
            "bars, so the 5-minute opening range could not be computed."
        )

    result_summary = {
        "strategy": ORB_TEMPLATE,
        "metrics": metrics,
        "trades": trades[:200],
        "data_quality_warnings": warnings,
        "lumibot": {k: v for k, v in (lumibot_results or {}).items()
                    if isinstance(v, (int, float, str, bool))},
    }

    update_backtest(
        bt_id,
        status="completed",
        completed_at=datetime.utcnow().isoformat(),
        result_json=json.dumps(result_summary),
    )
    insert_log("backtest", f"ORB backtest {bt_id} completed ({metrics['total_trades']} trades)",
               details={"metrics": metrics, "warnings": warnings[:5]})


def _resolve_backtesting_source(data_source: str, *, timestep: str = "day"):
    if data_source != "alpaca":
        return None, None, "Only Alpaca is supported as an active backtesting data source on this branch."
    service = AlpacaService(state.get_config())
    if not service.credential_status()["configured"]:
        return (
            None,
            None,
            "Alpaca credentials are not configured. Set ALPACA_API_KEY and ALPACA_API_SECRET, or ALPACA_OAUTH_TOKEN, to run Alpaca backtests.",
        )
    from lumibot.backtesting.alpaca_backtesting import AlpacaBacktesting

    return AlpacaBacktesting, service.lumibot_config(paper=True) | {"PAPER": True, "timestep": timestep}, None
