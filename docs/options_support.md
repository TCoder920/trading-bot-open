# Options Support

Options have **full strategy-facing trading rails** on Alpaca: contract discovery, quotes, single-leg
and multi-leg order construction, risk sizing, and managed take-profit / stop-loss exits. **All
trading is strategy-driven — there is no manual trading in the bot** (no UI ticket, no
order-placement HTTP endpoint). Manual trades are done outside the bot (Alpaca directly). An
autonomous options *strategy* is not built yet; the rails are ready for one. See
`docs/development/OPTIONS_AND_CRYPTO_TRADING.md` for the engineering reference.

## Present (strategy-facing, in-process)

- Contract discovery + quotes: `backend/services/options_service.py` (Alpaca `get_option_contracts`,
  `OptionLatestQuoteRequest`; no fabrication).
- Order construction: single-leg (OCC contract symbol, whole contracts) and multi-leg
  (`OrderClass.MLEG` + per-leg `OptionLegRequest`) in `alpaca_service`.
- Submission: `backend/services/asset_orders.py` `AssetOrderService.place_order(...)` — idempotent,
  risk-checked, with optional take-profit / stop-loss stored as managed-exit metadata. Strategies
  call this directly.
- Managed TP/SL exits via `backend/services/position_manager.py` (broker-agnostic; fires a closing
  order when the watched option price crosses a level — only on real quotes).
- Risk: premium sizing (`premium x 100 x contracts`) flows through the kill switch; optional
  `options.max_order_notional` cap.
- UI: the **Options** page is **reference + quick-settings only** (positions, order history,
  enable/paper/live/approval toggles). No order entry.

## Order rules (Alpaca)

- Orders use the **OCC contract symbol** (e.g. `AAPL250117C00150000`); **100x** multiplier.
- Sizing is **whole contracts** (no notional). `time_in_force=day`. **No extended hours.**
- Stop intents are downgraded to limit (plain stop is unreliable on options).

## Defaults

- `enabled: true`, `paper_enabled: true`, `live_enabled: false`
- `require_explicit_enablement: true`, `explicit_enablement: true`
- `approval_status: pending`, `account_approved: false` (broker-connected options blocked until approved)
- `allow_multileg_orders: true`
- `max_order_notional:` (empty = no per-order cap beyond the global limit)

## Not present yet

- An autonomous options **strategy** (the execution rails exist; the strategy that decides what to
  trade does not yet).
- Live options trading (requires options gates + global live gates).
- Manual options trading inside the bot (by design — use Alpaca directly).
- Native broker bracket orders (TP/SL is managed in-app instead, for cross-asset consistency).
