"""Stocks In Play ORB v1 routes: candidates, proposals, diagnostics, runtime
state, reset, and the proposal -> orders bridge.

Proposal-first design: this module never places live broker orders. Promoting a
proposal creates a row in the existing Alpaca order workflow.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend import state
from backend.database import (
    get_orb_proposal,
    get_orb_proposals,
    get_orb_runtime_state,
    get_watchlist,
    insert_log,
    insert_order,
    insert_orb_proposal,
    reset_orb_state,
    set_orb_runtime_state,
    update_orb_proposal,
    update_order,
)
from backend.models import OrbGenerateRequest, OrbResetRequest
from lumibot.custom_config.risk_engine import RiskEngine
from lumibot.custom_strategies.orb_engine import ORB_DEFAULTS
from lumibot.custom_strategies.orb_runtime import OrbSimulationService
from lumibot.custom_strategies.stocks_in_play_orb_v1 import STRATEGY_ID

router = APIRouter(prefix="/api/orb", tags=["orb"])


def _merged_config(overrides: dict | None = None) -> dict:
    """ORB defaults <- defaults.yaml block <- request overrides."""
    cfg = state.get_config()
    merged = {**ORB_DEFAULTS}
    merged.update(cfg.get(STRATEGY_ID, {}) or {})
    if overrides:
        merged.update({k: v for k, v in overrides.items() if k in ORB_DEFAULTS})
    return merged


def _parse_time(value: str | None):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


@router.get("/config")
def orb_config():
    """Effective ORB parameter set (defaults merged with config block)."""
    return {"strategy_id": STRATEGY_ID, "config": _merged_config()}


@router.get("/status")
def orb_status():
    rt = get_orb_runtime_state(STRATEGY_ID)
    proposals = get_orb_proposals(limit=500)
    pending = [p for p in proposals if p["status"] == "pending"]
    rejected = [p for p in proposals if p["status"] == "rejected"]
    candidates = (rt or {}).get("state", {}).get("candidates", []) if rt else []
    return {
        "strategy_id": STRATEGY_ID,
        "has_runtime_state": rt is not None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "proposal_count": len(pending),
        "rejected_count": len(rejected),
        "trace_stats": (rt or {}).get("state", {}).get("trace_stats") if rt else None,
        "session": {
            "opening_range": f"{_merged_config()['opening_range_start']}-{_merged_config()['opening_range_end']} ET",
            "entry_window": f"{_merged_config()['entry_window_start']}-{_merged_config()['entry_window_end']} ET",
            "flatten_time": f"{_merged_config()['flatten_time']} ET",
        },
    }


@router.get("/candidates")
def orb_candidates():
    rt = get_orb_runtime_state(STRATEGY_ID)
    if not rt:
        return {"candidates": [], "states": {}}
    st = rt.get("state", {})
    return {"candidates": st.get("candidates", []), "states": st.get("states", {})}


@router.get("/proposals")
def orb_proposals(status: str | None = None, trade_date: str | None = None, limit: int = 200):
    return {"proposals": get_orb_proposals(status=status, trade_date=trade_date, limit=limit)}


@router.get("/diagnostics")
def orb_diagnostics(trade_date: str | None = None):
    proposals = get_orb_proposals(trade_date=trade_date, limit=1000)
    pending = [p for p in proposals if p["status"] == "pending"]
    rejected = [p for p in proposals if p["status"] == "rejected"]

    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    reasons: dict[str, int] = {}
    for p in rejected:
        r = p.get("rejection_reason") or "unknown"
        reasons[r] = reasons.get(r, 0) + 1

    return {
        "total_proposals": len(proposals),
        "pending": len(pending),
        "rejected": len(rejected),
        "avg_rvol": _avg([p.get("rvol") for p in proposals]),
        "avg_spread": _avg([p.get("spread") for p in proposals]),
        "rejection_reasons": reasons,
        "data_quality_flag_counts": _flag_counts(proposals),
    }


def _flag_counts(proposals: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for p in proposals:
        for f in p.get("data_quality_flags", []) or []:
            counts[f] = counts.get(f, 0) + 1
    return counts


@router.get("/runtime-state")
def orb_runtime_state(trade_date: str | None = None):
    rt = get_orb_runtime_state(STRATEGY_ID, trade_date)
    if not rt:
        return {"strategy_id": STRATEGY_ID, "state": None}
    return rt


@router.post("/generate")
def orb_generate(body: OrbGenerateRequest):
    """Run the ORB engine over supplied market-data snapshots (simulation).

    Snapshots are sourced by the caller or Alpaca data integrations. This
    endpoint persists proposals and updates runtime state. It does NOT place
    any orders.
    """
    config = _merged_config(body.config)
    watchlist = set(get_watchlist("stocks"))
    # enforce watchlist membership when the watchlist is non-empty
    for snap in body.snapshots:
        if watchlist and snap.get("symbol", "").upper() not in watchlist:
            snap["in_watchlist"] = False
        else:
            snap.setdefault("in_watchlist", True)

    service = OrbSimulationService(config)
    result = service.evaluate_snapshots(
        body.snapshots,
        regime_state=body.regime_state,
        equity=body.equity,
        now_time=_parse_time(body.now_time),
        is_live=False,
    )

    saved = []
    for proposal in result["proposals"]:
        row = insert_orb_proposal(proposal, mode="simulation")
        saved.append(row)
    set_orb_runtime_state(STRATEGY_ID, {
        "candidates": result["candidates"],
        "states": result["states"],
        "trace_stats": result["trace_stats"],
    })
    insert_log(
        "strategy",
        f"ORB generated {len([p for p in saved if p['status']=='pending'])} proposals, "
        f"{len([p for p in saved if p['status']=='rejected'])} rejected",
        strategy=STRATEGY_ID,
        details={"candidates": result["candidates"]},
    )
    return {
        "candidates": result["candidates"],
        "proposals": saved,
        "trace_stats": result["trace_stats"],
    }


@router.post("/proposals/{proposal_id}/promote")
def promote_proposal(proposal_id: int):
    """Bridge a pending ORB proposal into the Alpaca order workflow."""
    proposal = get_orb_proposal(proposal_id)
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    if proposal["status"] != "pending":
        raise HTTPException(400, f"Cannot promote a '{proposal['status']}' proposal")
    if proposal.get("order_id"):
        raise HTTPException(400, "Proposal already promoted to an order")

    cfg = state.get_config()
    risk = RiskEngine(cfg)
    qty = proposal.get("quantity") or 0
    entry = proposal.get("proposed_entry") or 0
    dollar_amt = round(qty * entry, 2)
    approved, reason = risk.approve_proposal(proposal["symbol"], dollar_amt, "stocks")

    order = insert_order(
        symbol=proposal["symbol"],
        side=proposal.get("side", "buy"),
        quantity=qty,
        dollar_amount=dollar_amt,
        order_type="market",
        strategy=proposal.get("strategy_id"),
        asset_class="stocks",
        broker="alpaca",
        paper=cfg.get("trading_mode") != "live",
        sizing_mode="whole_share",
    )

    if approved:
        require_review = cfg.get("require_order_review", True)
        exec_status = "risk_approved" if require_review else "pending_broker_submission"
        review_status = "pending" if require_review else "reviewed"
        risk_status = "approved"
    else:
        exec_status = "risk_rejected"
        review_status = "pending"
        risk_status = "rejected"

    update_order(
        order["id"],
        risk_approved=int(approved),
        risk_status=risk_status,
        risk_reason=reason,
        execution_status=exec_status,
        review_status=review_status,
    )
    update_orb_proposal(proposal_id, status="approved" if approved else "rejected",
                        order_id=order["id"],
                        rejection_reason=None if approved else reason)
    insert_log(
        "order",
        f"ORB proposal {proposal_id} promoted to order {order['id']}: {proposal['symbol']}",
        symbol=proposal["symbol"], strategy=proposal.get("strategy_id"),
        details={"approved": approved, "reason": reason, "dollar_amount": dollar_amt},
    )
    return {"proposal": get_orb_proposal(proposal_id), "order": order["id"],
            "risk_approved": approved, "risk_reason": reason}


@router.post("/reset")
def orb_reset(body: OrbResetRequest | None = None):
    td = body.trade_date if body else None
    result = reset_orb_state(STRATEGY_ID, td)
    insert_log("strategy", f"ORB daily state reset ({result['trade_date']})", strategy=STRATEGY_ID)
    return result


@router.post("/reconcile")
def orb_reconcile(body: dict):
    """Reconcile internal positions vs broker positions.

    Body: {"internal": [{symbol, quantity}], "broker": [{symbol, quantity}],
           "tolerance": 1}. If a mismatch exceeds tolerance the response flags a
    kill-switch recommendation.
    """
    internal = {p["symbol"].upper(): float(p.get("quantity", 0)) for p in body.get("internal", [])}
    broker = {p["symbol"].upper(): float(p.get("quantity", 0)) for p in body.get("broker", [])}
    tolerance = float(body.get("tolerance", 0))
    mismatches = []
    for sym in set(internal) | set(broker):
        diff = abs(internal.get(sym, 0.0) - broker.get(sym, 0.0))
        if diff > tolerance:
            mismatches.append({"symbol": sym, "internal": internal.get(sym, 0.0),
                               "broker": broker.get(sym, 0.0), "diff": diff})
    kill = len(mismatches) > 0
    if kill:
        insert_log("strategy", f"ORB reconciliation mismatch: {len(mismatches)} symbols",
                   strategy=STRATEGY_ID, level="error", details={"mismatches": mismatches})
    return {"ok": not kill, "kill_switch_recommended": kill, "mismatches": mismatches}


@router.post("/flatten")
def orb_flatten():
    """Emergency flatten scaffold: marks pending proposals invalidated and logs
    the intent. Actual position exits must still be created and submitted
    through the Orders workflow."""
    pending = get_orb_proposals(status="pending", limit=1000)
    for p in pending:
        update_orb_proposal(p["id"], status="invalidated", invalidation_reason="manual_flatten")
    insert_log("strategy", "ORB emergency flatten requested (MANUAL_FLATTEN)",
               strategy=STRATEGY_ID, level="error",
               details={"invalidated_pending": len(pending)})
    return {"status": "flatten_requested", "invalidated_pending": len(pending),
            "note": "Position exits remain routed through the Orders workflow."}
