"""Alpaca status, account, data, and asset-class routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.services.broker_factory import get_broker_service
from backend.services.data_provider_factory import get_data_provider_service

router = APIRouter(tags=["alpaca"])


def _broker():
    return get_broker_service(state.get_config())


def _data():
    return get_data_provider_service(state.get_config())


@router.get("/api/alpaca/status")
def alpaca_status():
    return _broker().broker_status()


@router.get("/api/alpaca/config")
def alpaca_config():
    cfg = state.get_config()
    return {
        "active_broker": cfg.get("active_broker"),
        "active_data_provider": cfg.get("active_data_provider"),
        "trading_mode": cfg.get("trading_mode"),
        "live_trading_enabled": cfg.get("live_trading_enabled"),
        "alpaca": cfg.get("alpaca", {}),
        "asset_classes": _broker().asset_classes(),
    }


@router.get("/api/alpaca/credentials")
def alpaca_credentials():
    return _broker().credential_status()


@router.get("/api/alpaca/account")
def alpaca_account():
    return _broker().account()


@router.get("/api/alpaca/positions")
def alpaca_positions():
    return _broker().positions()


@router.get("/api/alpaca/orders")
def alpaca_orders():
    return _broker().orders()


@router.get("/api/alpaca/assets/{symbol}")
def alpaca_asset(symbol: str):
    return _broker().asset_metadata(symbol)


@router.get("/api/alpaca/data/status")
def alpaca_data_status():
    return _data().data_status()


@router.post("/api/alpaca/test-connection")
def alpaca_test_connection():
    return _broker().test_connection()


@router.get("/api/assets/classes")
def asset_classes():
    return {"asset_classes": _broker().asset_classes()}


@router.get("/api/assets/stocks/status")
def stocks_status():
    return _asset_status("stocks")


@router.get("/api/assets/options/status")
def options_status():
    return _asset_status("options")


@router.get("/api/assets/crypto/status")
def crypto_status():
    return _asset_status("crypto")


def _asset_status(asset_class: str) -> dict:
    service = _broker()
    match = next((a for a in service.asset_classes() if a["asset_class"] == asset_class), None)
    return match or {"asset_class": asset_class, "enabled": False, "ready": False}
