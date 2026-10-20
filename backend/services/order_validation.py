"""Centralized order validation and normalization."""

from __future__ import annotations

from dataclasses import dataclass

from backend.models import OrderProposal
from backend.services.exposure_service import ExposureService
from backend.services.broker_factory import get_broker_service
from lumibot.custom_config.risk_engine import RiskEngine


class OrderValidationError(ValueError):
    pass


@dataclass
class OrderValidationResult:
    normalized: dict
    risk_approved: bool
    risk_reason: str
    broker_payload: dict | None
    exposure: dict | None = None

    def to_dict(self) -> dict:
        return {
            "valid": True,
            "normalized": self.normalized,
            "risk_approved": self.risk_approved,
            "risk_reason": self.risk_reason,
            "broker_payload": self.broker_payload,
            "exposure": self.exposure,
        }


def positive_float(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OrderValidationError(f"{field} must be a positive number.")
    if number <= 0:
        raise OrderValidationError(f"{field} must be a positive number.")
    return number


def normalize_order_proposal(body: OrderProposal, cfg: dict) -> dict:
    asset_class = (body.asset_class or "").strip().lower()
    if not asset_class:
        raise OrderValidationError("asset_class is required.")
    if asset_class not in {"stocks", "options", "crypto"}:
        raise OrderValidationError(f"Unsupported asset_class '{asset_class}'.")

    quantity = body.quantity
    notional_input = body.notional if body.notional is not None else body.dollar_amount
    normalized = {
        "asset_class": asset_class,
        "symbol": body.symbol.upper(),
        "side": body.side,
        "quantity": quantity,
        "dollar_amount": body.dollar_amount,
        "notional": body.notional,
        "sizing_mode": body.sizing_mode,
        "order_type": body.order_type,
        "time_in_force": body.time_in_force or "day",
        "risk_amount": float(notional_input or quantity or 0),
        "metadata": {},
    }

    if asset_class == "stocks":
        sizing_mode = body.sizing_mode or cfg.get("stocks", {}).get("sizing_mode", "notional")
        if quantity is not None and body.notional is not None:
            raise OrderValidationError("Stock orders cannot include both quantity and notional.")
        if quantity is not None or sizing_mode in {"whole_share", "quantity"}:
            qty = positive_float(quantity, "quantity")
            if not qty.is_integer():
                raise OrderValidationError("Stock quantity must be a whole-share count.")
            risk_amount = positive_float(body.dollar_amount, "dollar_amount")
            normalized.update({
                "quantity": int(qty),
                "dollar_amount": body.dollar_amount,
                "notional": None,
                "sizing_mode": "whole_share",
                "risk_amount": risk_amount,
            })
            return normalized
        if sizing_mode != "notional":
            raise OrderValidationError("Unsupported stock sizing mode.")
        notional = positive_float(notional_input, "notional")
        min_notional = float(cfg.get("stocks", {}).get("min_order_notional", 1.0))
        if notional < min_notional:
            raise OrderValidationError(f"Stock notional must be at least {min_notional}.")
        asset = get_broker_service(cfg).asset_metadata(body.symbol)
        if not asset.get("fractionable"):
            raise OrderValidationError(f"{body.symbol.upper()} is not fractionable for stock notional trading.")
        normalized.update({
            "quantity": None,
            "dollar_amount": notional,
            "notional": notional,
            "sizing_mode": "notional",
            "time_in_force": "day",
            "risk_amount": notional,
            "metadata": {"asset_metadata": asset},
        })
        return normalized

    if asset_class == "options":
        if notional_input is not None:
            raise OrderValidationError("Options orders cannot use notional sizing.")
        qty = positive_float(quantity, "quantity")
        if not qty.is_integer():
            raise OrderValidationError("Options quantity must be a whole contract count.")
        normalized.update({
            "quantity": int(qty),
            "dollar_amount": None,
            "notional": None,
            "sizing_mode": "contracts",
            "risk_amount": float(body.premium or 1) * int(qty) * 100,
        })
        return normalized

    if notional_input is not None:
        notional = positive_float(notional_input, "notional")
        normalized.update({
            "notional": notional,
            "dollar_amount": body.dollar_amount,
            "risk_amount": notional,
        })
    elif quantity is not None:
        qty = positive_float(quantity, "quantity")
        normalized.update({"quantity": qty, "risk_amount": qty})
    else:
        raise OrderValidationError("Crypto orders require quantity or notional.")
    normalized["sizing_mode"] = body.sizing_mode or "crypto"
    return normalized


def validate_order_preview(body: OrderProposal, cfg: dict) -> OrderValidationResult:
    normalized = normalize_order_proposal(body, cfg)
    risk = RiskEngine(cfg)
    risk_approved, risk_reason = risk.approve_proposal(
        normalized["symbol"],
        normalized["risk_amount"],
        normalized["asset_class"],
    )
    exposure = None
    if risk_approved:
        exposure_approved, exposure_reason, exposure = ExposureService(cfg).approve_order_amount(
            normalized["risk_amount"],
            side=body.side,
        )
        if not exposure_approved:
            risk_approved = False
            risk_reason = exposure_reason
        else:
            normalized["metadata"] = {
                **(normalized.get("metadata") or {}),
                "exposure": exposure,
                "exposure_reason": exposure_reason,
            }
    payload_order = {
        "id": "preview",
        "symbol": normalized["symbol"],
        "side": body.side,
        "asset_class": normalized["asset_class"],
        "quantity": normalized["quantity"],
        "dollar_amount": normalized["dollar_amount"],
        "notional": normalized["notional"],
        "sizing_mode": normalized["sizing_mode"],
        "order_type": body.order_type,
        "time_in_force": normalized["time_in_force"],
        "limit_price": body.limit_price,
        "stop_price": body.stop_price,
        "underlying_symbol": body.underlying_symbol,
        "option_type": body.option_type,
        "strike": body.strike,
        "expiration": body.expiration,
        "premium": body.premium,
        "quote_currency": body.quote_currency,
    }
    broker_payload = None
    if risk_approved:
        broker_payload = get_broker_service(cfg).prepare_order_payload(payload_order)
        broker_payload.pop("client_order_id", None)
    return OrderValidationResult(normalized, risk_approved, risk_reason, broker_payload, exposure)
