# Crypto Support

Crypto has **full strategy-facing trading rails** on Alpaca: quotes, bars, order construction
(market / limit / stop-limit, notional or fractional quantity), risk sizing, and managed
take-profit / stop-loss exits that run 24/7. **All trading is strategy-driven — there is no manual
trading in the bot** (no UI ticket, no order-placement HTTP endpoint). Manual trades are done
outside the bot (Alpaca directly). An autonomous crypto *strategy* is not built yet; the rails are
ready for one. See `docs/development/OPTIONS_AND_CRYPTO_TRADING.md` for the reference.

## Present (strategy-facing, in-process)

- Quotes/bars: `backend/services/crypto_service.py` (latest bid/ask/mid + recent daily bars; no fabrication).
- Order construction: 24/7 crypto orders (pair symbols, `tif=gtc`, notional/fractional) in `alpaca_service`.
- Submission: `backend/services/asset_orders.py` `AssetOrderService.place_order(...)` — idempotent,
  risk-checked, with optional take-profit / stop-loss stored as managed-exit metadata. Strategies
  call this directly.
- Managed TP/SL exits via `backend/services/position_manager.py` — runs every loop tick, **24/7**,
  and fires a closing order when the watched price crosses a level (only on real quotes).
- Risk: notional sizing flows through the kill switch; optional `crypto.max_order_notional` cap.
- UI: the **Crypto** page is **reference + quick-settings only** (positions, order history,
  enable/paper/live toggles). No order entry.

## Order rules (Alpaca)

- Symbols are pair form (`BTC/USD`, `ETH/USD`). Trades **24/7**.
- `time_in_force=gtc` (a `day` request is converted to `gtc`). **No extended-hours flag.**
- Supports **notional** (market only) and **fractional quantity**.
- Plain stop / market-stop are unsupported; stop intents are handled via stop-limit or managed exits.

## Defaults

- `enabled: true`, `paper_enabled: false`, `live_enabled: false`
- `require_explicit_enablement: true`, `explicit_enablement: false`
- `allowed_symbols: [BTC/USD, ETH/USD]`
- `max_notional_per_trade: 100`, `max_order_notional:` (empty = no extra per-order cap)

Enable crypto paper trading by setting `crypto.explicit_enablement: true` and
`crypto.paper_enabled: true` (Settings UI / config). Live crypto additionally needs the global
live gates.

## Not present yet

- An autonomous crypto **strategy** (the execution rails exist; the strategy that decides what to
  trade does not yet).
- Live crypto trading (requires crypto gates + global live gates).
- Manual crypto trading inside the bot (by design — use Alpaca directly).
