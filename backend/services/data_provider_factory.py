"""Data provider factory for the Alpaca-only app branch."""

from __future__ import annotations

from backend.services.alpaca_service import AlpacaService


def get_data_provider_service(cfg: dict) -> AlpacaService:
    if cfg.get("active_data_provider", "alpaca") != "alpaca":
        raise ValueError("Only Alpaca is supported on this branch.")
    return AlpacaService(cfg)
