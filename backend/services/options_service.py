"""Alpaca options support: contract discovery + option quotes.

NO-FABRICATION RULE (CLAUDE.md RULE #1): contract lists and quotes come only from Alpaca.
When credentials are missing or Alpaca returns nothing, we return empty results with an
explicit warning — never invented strikes, expirations, or prices.

Alpaca specifics (alpaca-py):
* Contracts: ``TradingClient.get_option_contracts(GetOptionContractsRequest(...))``.
* Option quotes: ``OptionHistoricalDataClient`` + ``OptionLatestQuoteRequest``.
* Orders use the OCC contract symbol (e.g. ``AAPL250117C00150000``); 100x multiplier.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.broker_factory import get_broker_service


@dataclass
class OptionsResult:
    contracts: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_page_token: str | None = None

    def to_dict(self) -> dict:
        return {"contracts": self.contracts, "warnings": self.warnings,
                "next_page_token": self.next_page_token}


@dataclass
class OptionsService:
    cfg: dict

    def _alpaca(self):
        return get_broker_service(self.cfg)

    def is_configured(self) -> bool:
        return bool(self._alpaca().credential_status().get("configured"))

    def list_contracts(
        self,
        underlying: str,
        *,
        option_type: str | None = None,
        expiration_date: str | None = None,
        expiration_gte: str | None = None,
        expiration_lte: str | None = None,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 100,
    ) -> OptionsResult:
        """Discover real option contracts for ``underlying`` from Alpaca."""
        result = OptionsResult()
        if self.cfg.get("trading_mode") == "simulation":
            result.warnings.append("simulation mode: option contracts not fetched from Alpaca")
            return result
        if not self.is_configured():
            result.warnings.append("Alpaca credentials not configured: no option contracts (no fabrication)")
            return result
        try:
            from alpaca.trading.enums import ContractType
            from alpaca.trading.requests import GetOptionContractsRequest

            kwargs: dict = {"underlying_symbols": [underlying.upper()], "limit": int(limit)}
            if option_type:
                kwargs["type"] = ContractType(option_type.lower())
            if expiration_date:
                kwargs["expiration_date"] = expiration_date
            if expiration_gte:
                kwargs["expiration_date_gte"] = expiration_gte
            if expiration_lte:
                kwargs["expiration_date_lte"] = expiration_lte
            if strike_gte is not None:
                kwargs["strike_price_gte"] = str(strike_gte)
            if strike_lte is not None:
                kwargs["strike_price_lte"] = str(strike_lte)
            req = GetOptionContractsRequest(**kwargs)
            api = self._alpaca()._build_broker().api
            resp = api.get_option_contracts(req)
        except Exception as exc:  # pragma: no cover - network/credential path
            result.warnings.append(f"option contract fetch failed: {exc}")
            return result

        raw = getattr(resp, "option_contracts", None)
        if raw is None and isinstance(resp, dict):
            raw = resp.get("option_contracts")
        for c in raw or []:
            result.contracts.append(self._contract_to_dict(c))
        result.next_page_token = getattr(resp, "next_page_token", None)
        if not result.contracts:
            result.warnings.append(f"no option contracts returned for {underlying.upper()}")
        return result

    def latest_quote(self, contract_symbol: str) -> dict:
        """Latest real bid/ask for an OCC option contract. Empty + warning if unavailable."""
        if self.cfg.get("trading_mode") == "simulation":
            return {"symbol": contract_symbol, "bid": None, "ask": None,
                    "warning": "simulation mode: no option quote"}
        if not self.is_configured():
            return {"symbol": contract_symbol, "bid": None, "ask": None,
                    "warning": "Alpaca credentials not configured: no option quote (no fabrication)"}
        try:  # pragma: no cover - network path
            from alpaca.data.historical import OptionHistoricalDataClient
            from alpaca.data.requests import OptionLatestQuoteRequest

            creds = self._alpaca()._selected_credentials()
            client = OptionHistoricalDataClient(creds["api_key"], creds["api_secret"])
            resp = client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=contract_symbol.upper())
            )
            q = resp.get(contract_symbol.upper())
            if q is None:
                return {"symbol": contract_symbol, "bid": None, "ask": None,
                        "warning": "no quote returned (gap left honest)"}
            bid = getattr(q, "bid_price", None)
            ask = getattr(q, "ask_price", None)
            mid = round((bid + ask) / 2, 4) if bid and ask else None
            return {"symbol": contract_symbol.upper(), "bid": bid, "ask": ask, "mid": mid}
        except Exception as exc:  # pragma: no cover
            return {"symbol": contract_symbol, "bid": None, "ask": None,
                    "warning": f"option quote fetch failed: {exc}"}

    @staticmethod
    def _contract_to_dict(c: object) -> dict:
        def g(name):
            if isinstance(c, dict):
                return c.get(name)
            return getattr(c, name, None)

        return {
            "symbol": g("symbol"),
            "underlying_symbol": g("underlying_symbol"),
            "type": str(g("type").value) if hasattr(g("type"), "value") else g("type"),
            "strike_price": float(g("strike_price")) if g("strike_price") is not None else None,
            "expiration_date": str(g("expiration_date")) if g("expiration_date") is not None else None,
            "style": str(g("style").value) if hasattr(g("style"), "value") else g("style"),
            "tradable": bool(g("tradable")) if g("tradable") is not None else None,
            "open_interest": g("open_interest"),
            "close_price": float(g("close_price")) if g("close_price") is not None else None,
        }
