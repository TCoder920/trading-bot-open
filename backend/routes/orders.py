"""Order workflow routes: proposal -> risk check -> broker submission."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import state
from backend.database import (
    get_order,
    get_orders,
    insert_broker_order_event,
    insert_log,
    insert_order,
    update_order,
)
from backend.models import OrderFailRequest, OrderProposal, OrderUpdate
from backend.services.broker_factory import get_broker_service
from backend.services.order_validation import (
    OrderValidationError,
    normalize_order_proposal,
    validate_order_preview,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


class ExecuteRequest(BaseModel):
    broker_order_id: str | None = None
    execution_status: str | None = None
    notes: str | None = None


class RejectRequest(BaseModel):
    reason: str = "Manually rejected"


TERMINAL_STATUSES = {"paper_filled", "live_filled", "rejected", "failed", "canceled", "risk_rejected"}
ALLOWED_TRANSITIONS = {
    "proposed": {"risk_approved", "risk_rejected"},
    "risk_approved": {"pending_broker_submission", "rejected", "canceled"},
    "pending_broker_submission": {"accepted", "paper_submitted", "live_submitted", "paper_filled", "live_filled", "failed", "rejected", "canceled"},
    "accepted": {"paper_filled", "live_filled", "partially_filled", "failed", "rejected", "canceled"},
    "paper_submitted": {"paper_filled", "partially_filled", "failed", "rejected", "canceled"},
    "live_submitted": {"live_filled", "partially_filled", "failed", "rejected", "canceled"},
    "partially_filled": {"paper_filled", "live_filled", "failed", "canceled"},
}


def _transition_order(order: dict, target_status: str, **fields):
    current = order.get("execution_status") or "proposed"
    if current in TERMINAL_STATUSES:
        raise HTTPException(400, f"Cannot transition terminal order from '{current}' to '{target_status}'")
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target_status != current and target_status not in allowed:
        raise HTTPException(400, f"Invalid order transition: {current} -> {target_status}")
    return update_order(order["id"], execution_status=target_status, **fields)


def _normalize_or_400(body: OrderProposal, cfg: dict) -> dict:
    try:
        return normalize_order_proposal(body, cfg)
    except OrderValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("")
def list_orders(status: str | None = None, limit: int = 100):
    return {"orders": get_orders(status=status, limit=limit)}


@router.post("/preview")
def preview_order(body: OrderProposal):
    cfg = state.get_config()
    try:
        return validate_order_preview(body, cfg).to_dict()
    except OrderValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{order_id}")
def read_order(order_id: int):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.post("/propose")
def propose_order(body: OrderProposal):
    cfg = state.get_config()
    try:
        validation = validate_order_preview(body, cfg)
    except OrderValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    normalized = validation.normalized
    dollar_amt = normalized["risk_amount"]
    approved = validation.risk_approved
    reason = validation.risk_reason

    order = insert_order(
        symbol=body.symbol,
        side=body.side,
        quantity=normalized["quantity"],
        dollar_amount=normalized["dollar_amount"],
        order_type=body.order_type,
        time_in_force=normalized["time_in_force"],
        strategy=body.strategy,
        strategy_id=body.strategy_id or body.strategy,
        asset_class=normalized["asset_class"],
        broker="alpaca",
        paper=cfg.get("trading_mode") != "live",
        sizing_mode=normalized["sizing_mode"],
        notional=normalized["notional"],
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        underlying_symbol=body.underlying_symbol,
        option_type=body.option_type,
        strike=body.strike,
        expiration=body.expiration,
        premium=body.premium,
        quote_currency=body.quote_currency,
        metadata=normalized["metadata"],
    )

    if approved:
        exec_status = "risk_approved" if cfg.get("require_order_review", True) else "pending_broker_submission"
        review_status = "pending" if cfg.get("require_order_review", True) else "reviewed"
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

    insert_log(
        "order",
        f"Order proposed: {body.side} {body.symbol} ${dollar_amt}",
        symbol=body.symbol,
        strategy=body.strategy,
        details={"approved": approved, "reason": reason, "status": exec_status, "broker": "alpaca"},
    )
    return get_order(order["id"])


@router.post("/{order_id}/review")
def review_order(order_id: int):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if not order.get("risk_approved"):
        raise HTTPException(400, "Cannot review order that failed risk check")

    _transition_order(
        order,
        "pending_broker_submission",
        review_status="reviewed",
        review_details_json=json.dumps({"reviewed_by": "ui"}),
    )
    insert_log("order", f"Order {order_id} reviewed", symbol=order["symbol"])
    return get_order(order_id)


@router.post("/{order_id}/advance")
def advance_order(order_id: int):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if not order.get("risk_approved"):
        raise HTTPException(400, "Order failed risk check")

    _transition_order(order, "pending_broker_submission", review_status="reviewed")

    insert_log("order", f"Order {order_id} advanced to broker submission queue", symbol=order["symbol"])
    return get_order(order_id)


@router.post("/{order_id}/place")
def place_order(order_id: int):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if not order.get("risk_approved"):
        raise HTTPException(400, "Order failed risk check")
    if order.get("execution_status") != "pending_broker_submission":
        raise HTTPException(400, "Order must be pending broker submission before placement")

    cfg = state.get_config()
    if order.get("review_status") != "reviewed" and cfg.get("require_order_review", True):
        update_order(order_id, execution_status="failed", error="Order must be reviewed before broker submission")
        return get_order(order_id)

    service = get_broker_service(cfg)
    result = service.submit_order(order)
    status = result.get("execution_status", "failed")
    details = result.get("details") or result
    fields = {
        "broker": "alpaca",
        "paper": int(bool(result.get("paper", cfg.get("trading_mode") != "live"))),
        "execution_details_json": json.dumps(details),
    }
    if result.get("broker_order_id"):
        fields["broker_order_id"] = result["broker_order_id"]
    if result.get("client_order_id"):
        fields["client_order_id"] = result["client_order_id"]
    if result.get("errors"):
        fields["error"] = "; ".join(result["errors"])
    insert_broker_order_event(
        order_id=order_id,
        event_type="submit",
        status=status,
        broker_order_id=result.get("broker_order_id"),
        client_order_id=result.get("client_order_id"),
        payload=details.get("payload") if isinstance(details, dict) else None,
        response=result,
        error=fields.get("error"),
    )
    _transition_order(order, status, **fields)
    insert_log("order", f"Order {order_id} broker submission result: {status}", symbol=order["symbol"], details=result)
    return get_order(order_id)


@router.post("/{order_id}/execute")
def mark_executed(order_id: int, body: ExecuteRequest | None = None):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    status = body.execution_status if body and body.execution_status else ("paper_filled" if order.get("paper", True) else "live_filled")
    fields = {"execution_status": status}
    if body:
        if body.broker_order_id:
            fields["broker_order_id"] = body.broker_order_id
        if body.notes:
            fields["notes"] = body.notes
    _transition_order(order, status, **{k: v for k, v in fields.items() if k != "execution_status"})
    insert_log("order", f"Order {order_id} marked {status}", symbol=order["symbol"])
    return get_order(order_id)


@router.post("/{order_id}/fail")
def mark_failed(order_id: int, body: OrderFailRequest):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    _transition_order(order, "failed", error=body.reason, notes=body.reason)
    insert_log("order", f"Order {order_id} failed: {body.reason}", symbol=order["symbol"], level="error")
    return get_order(order_id)


@router.post("/{order_id}/reject")
def reject_order(order_id: int, body: RejectRequest | None = None):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    reason = body.reason if body else "Manually rejected"
    _transition_order(order, "rejected", error=reason, notes=reason)
    insert_log("order", f"Order {order_id} rejected: {reason}", symbol=order["symbol"])
    return get_order(order_id)


@router.post("/{order_id}/cancel")
def cancel_order(order_id: int):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    _transition_order(order, "canceled", notes="Canceled via UI")
    insert_log("order", f"Order {order_id} canceled", symbol=order["symbol"])
    return get_order(order_id)


@router.patch("/{order_id}")
def patch_order(order_id: int, body: OrderUpdate):
    order = get_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    fields = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if fields:
        update_order(order_id, **fields)
    return get_order(order_id)
