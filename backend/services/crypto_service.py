"""Alpaca crypto market data: latest quotes and recent bars.

NO-FABRICATION RULE (CLAUDE.md RULE #1): quotes/bars come only from Alpaca. When data is
unavailable we return empty + an explicit warning, never invented prices.

Alpaca specifics (alpaca-py): crypto symbols are pair form (``BTC/USD``); crypto trades 24/7;
``CryptoHistoricalDataClient`` serves quotes/bars.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.broker_factory import get_broker_service


@dataclass
class CryptoService:
    cfg: dict

    def _alpaca(self):
        return get_broker_service(self.cfg)

    def is_configured(self) -> bool:
        return bool(self._alpaca().credential_status().get("configured"))

    def _client(self):  # pragma: no cover - network path
        from alpaca.data.historical import CryptoHistoricalDataClient

        creds = self._alpaca()._selected_credentials()
        # Crypto data is available without keys, but use configured creds when present.
        if creds.get("api_key") and creds.get("api_secret"):
            return CryptoHistoricalDataClient(creds["api_key"], creds["api_secret"])
        return CryptoHistoricalDataClient()

    def latest_quote(self, symbol: str) -> dict:
        """Latest real bid/ask/mid for a crypto pair. Empty + warning if unavailable."""
        sym = symbol.upper()
        if self.cfg.get("trading_mode") == "simulation":
            return {"symbol": sym, "bid": None, "ask": None, "mid": None,
                    "warning": "simulation mode: no crypto quote"}
        try:  # pragma: no cover - network path
            from alpaca.data.requests import CryptoLatestQuoteRequest

            client = self._client()
            resp = client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=sym))
            q = resp.get(sym)
            if q is None:
                return {"symbol": sym, "bid": None, "ask": None, "mid": None,
                        "warning": "no crypto quote returned (gap left honest)"}
            bid = getattr(q, "bid_price", None)
            ask = getattr(q, "ask_price", None)
            mid = round((bid + ask) / 2, 6) if bid and ask else None
            return {"symbol": sym, "bid": bid, "ask": ask, "mid": mid}
        except Exception as exc:  # pragma: no cover
            return {"symbol": sym, "bid": None, "ask": None, "mid": None,
                    "warning": f"crypto quote fetch failed: {exc}"}

    def recent_bars(self, symbol: str, *, limit: int = 100) -> dict:
        """Recent daily bars for a crypto pair (real data only)."""
        sym = symbol.upper()
        if self.cfg.get("trading_mode") == "simulation":
            return {"symbol": sym, "bars": [], "warning": "simulation mode: no crypto bars"}
        try:  # pragma: no cover - network path
            from datetime import datetime, timedelta, timezone

            from alpaca.data.requests import CryptoBarsRequest
            from alpaca.data.timeframe import TimeFrame

            client = self._client()
            start = datetime.now(timezone.utc) - timedelta(days=int(limit))
            resp = client.get_crypto_bars(
                CryptoBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=start)
            )
            rows = resp.data.get(sym, []) if hasattr(resp, "data") else []
            bars = [{"time": b.timestamp.isoformat(), "open": b.open, "high": b.high,
                     "low": b.low, "close": b.close, "volume": b.volume} for b in rows]
            out = {"symbol": sym, "bars": bars}
            if not bars:
                out["warning"] = "no crypto bars returned (gap left honest)"
            return out
        except Exception as exc:  # pragma: no cover
            return {"symbol": sym, "bars": [], "warning": f"crypto bar fetch failed: {exc}"}
