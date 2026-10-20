"""Alpaca data source info routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend import state
from backend.services.data_provider_factory import get_data_provider_service

router = APIRouter(prefix="/api/datasources", tags=["datasources"])


@router.get("")
def list_datasources():
    service = get_data_provider_service(state.get_config())
    status = service.data_status()
    return {
        "datasources": [
            {
                "key": "alpaca",
                "label": "Alpaca",
                "type": "broker_market_data",
                "supported": True,
                "configured": status["configured"],
                "fields": [],
                "tooltip": "Native Lumibot Alpaca market data for stocks, options, and crypto. Credentials come from environment variables.",
                "capabilities": status["capabilities"],
            }
        ]
    }
