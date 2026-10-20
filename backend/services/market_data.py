"""Alpaca market-data access for the autonomous loop.

NO-FABRICATION RULE (CLAUDE.md RULE #1): this module returns only real bars/quotes
fetched from Alpaca. When data is unavailable (no credentials, sparse extended-hours
tape, provider error), it returns empty results and records an explicit
``data_quality_warnings`` entry. It NEVER invents, forward-fills, or interpolates a bar.

Feed selection: outside regular trading hours we use the configured
``extended_hours_data_feed`` (``sip`` by default) because ``iex`` is sparse in
pre/post-market. Alpaca is the only provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.broker_factory import get_broker_service


@dataclass
class MarketDataResult:
    snapshots: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    feed: str | None = None

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


@dataclass
class MarketDataService:
    """Fetches ORB-shaped market-data snapshots from Alpaca (real data only)."""

    cfg: dict

    def is_configured(self) -> bool:
        return bool(get_broker_service(self.cfg).credential_status().get("configured"))

    def feed_for(self, *, extended_hours: bool) -> str:
        return get_broker_service(self.cfg).effective_data_feed(extended_hours=extended_hours)

    def snapshots(self, symbols: list[str], *, extended_hours: bool = False) -> MarketDataResult:
        """Return ORB snapshots for ``symbols``.

        In simulation mode or without credentials we cannot fetch real bars, so we return
        an empty result with an explicit warning rather than fabricating data.
        """
        result = MarketDataResult(feed=self.feed_for(extended_hours=extended_hours))
        mode = self.cfg.get("trading_mode", "simulation")
        if mode == "simulation":
            result.add_warning("simulation mode: no live Alpaca data fetched (use /api/orb/generate snapshots)")
            return result
        if not self.is_configured():
            result.add_warning("Alpaca credentials not configured: no market data available (no fabrication)")
            return result
        try:
            client = self._data_client()
        except Exception as exc:  # pragma: no cover - import/credential errors
            result.add_warning(f"Alpaca data client unavailable: {exc}")
            return result

        for symbol in symbols:
            snap = self._symbol_snapshot(client, symbol, result.feed, result)
            if snap is not None:
                result.snapshots.append(snap)
        return result

    # ── internals ────────────────────────────────────────────────────────
    def _data_client(self):  # pragma: no cover - requires alpaca-py + creds
        from alpaca.data.historical import StockHistoricalDataClient

        creds = get_broker_service(self.cfg)._selected_credentials()
        return StockHistoricalDataClient(creds["api_key"], creds["api_secret"])

    def _symbol_snapshot(self, client, symbol: str, feed: str, result: MarketDataResult) -> dict | None:  # pragma: no cover
        """Build a single ORB snapshot from real Alpaca bars/quotes.

        Returns ``None`` (and records a warning) when no real bars exist — never a
        fabricated placeholder.
        """
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
        from alpaca.data.timeframe import TimeFrame

        et = ZoneInfo("America/New_York")
        now = datetime.now(et)
        feed_enum = DataFeed.SIP if feed == "sip" else DataFeed.IEX
        try:
            bars_req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                feed=feed_enum,
            )
            bar_set = client.get_stock_bars(bars_req)
            rows = bar_set.data.get(symbol, []) if hasattr(bar_set, "data") else []
        except Exception as exc:
            result.add_warning(f"{symbol}: bar fetch failed ({exc})")
            return None

        session_bars: list[dict] = []
        for b in rows:
            ts = b.timestamp.astimezone(et)
            session_bars.append({
                "time": ts.time(),
                "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "volume": b.volume,
            })
        if not session_bars:
            result.add_warning(f"{symbol}: no real bars on the {feed} feed for this session (gap left honest)")
            return None

        bid = ask = last = None
        try:
            q = client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=feed_enum))
            quote = q.get(symbol)
            if quote is not None:
                bid, ask = quote.bid_price, quote.ask_price
        except Exception as exc:
            result.add_warning(f"{symbol}: quote fetch failed ({exc})")
        last = session_bars[-1]["close"]

        or_bars = [b for b in session_bars if _between(b["time"], "09:30", "09:35")]
        return {
            "symbol": symbol.upper(),
            "opening_range_bars": or_bars,
            "session_bars": session_bars,
            "price": last,
            "bid": bid,
            "ask": ask,
            "data_fresh": True,
        }


def _between(t, start: str, end: str) -> bool:
    from datetime import datetime

    s = datetime.strptime(start, "%H:%M").time()
    e = datetime.strptime(end, "%H:%M").time()
    return s <= t < e
