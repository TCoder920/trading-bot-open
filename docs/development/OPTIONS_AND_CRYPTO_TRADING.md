# Options & Crypto Trading Capability

One-line description: Implementation plan + reference for enabling real Alpaca options and
crypto trading rails in trading-bot2 (place/manage individual option and crypto orders with
take-profit / stop-loss exits), independent of any specific strategy.

- Last Updated: 2026-06-15
- Status: Complete (capability rails; strategies still TODO)
- Audience: Engineers / AI agents working on trading-bot2 (Alpaca-only branch `alpaca-bot`)

## Overview

Previously, options and crypto were *scaffolding only* (status metadata + partial payload
fields). The autonomous loop and the real broker submit path were stocks-only. This change set
adds the **strategy-facing capability rails** so that an options or crypto strategy can execute on
Alpaca PAPER — place a contract/pair order and exit at a target or stop — correctly per Alpaca's
API, with managed exits.

**All bot trading is strategy-driven.** There is intentionally **no manual trading in the bot**:
no UI order ticket and no order-placement HTTP endpoint. Manual trading is done outside the bot
(Alpaca directly). The strategy entry point is `AssetOrderService.place_order(...)` (in-process).
Strategies themselves are out of scope here; this is about making the trading *possible and
correct*. The Options/Crypto UI pages are reference + quick-settings views only.

### Hard invariants (do not violate)

- **No fabricated market data.** Missing option/crypto quotes/bars surface as empty + explicit
  warning, never invented values.
- Alpaca is the only broker and only data provider.
- `live_trading_enabled=false`, `trading_mode=simulation` by default. Simulation stays fully
  mocked. Real submission validated against Alpaca PAPER only; live separately gated.
- Options/crypto live trading stays disabled unless explicitly enabled and validated.

## Alpaca SDK facts (confirmed against installed alpaca-py 0.43.4)

### Options
- Contract discovery: `TradingClient.get_option_contracts(GetOptionContractsRequest(...))` with
  `underlying_symbols`, `expiration_date[/_gte/_lte]`, `strike_price_gte/_lte`,
  `type=ContractType.CALL|PUT`, `style`, `status`, `limit`.
- Option market data: `OptionHistoricalDataClient` + `OptionLatestQuoteRequest`.
- Orders use the **OCC contract symbol** (e.g. `AAPL250117C00150000`) as `symbol` in a normal
  `MarketOrderRequest`/`LimitOrderRequest`. Contracts have a **100x multiplier**.
- Multi-leg: `order_class=OrderClass.MLEG` + `legs=[OptionLegRequest(symbol, side, ratio_qty,
  position_intent)]`.
- Sizing is in **whole contracts** (no notional). **No `extended_hours`** for options.

### Crypto
- Symbols are pair form, e.g. `BTC/USD`, `ETH/USD`.
- Crypto market data: `CryptoHistoricalDataClient` + `CryptoLatestQuoteRequest`/`CryptoBarsRequest`
  (no credentials required for crypto data, but we still use configured creds when present).
- Orders: `market`, `limit`, `stop_limit`. Trades **24/7**. Supports **fractional qty** and
  **notional**. `time_in_force` is `gtc` (or `ioc`); **not** `day`. **No `extended_hours`**.

### Take-profit / stop-loss
- Native bracket (`order_class=bracket`, `TakeProfitRequest`, `StopLossRequest`) is supported for
  equities and single-leg options but **not crypto**.
- For cross-asset reliability we manage TP/SL in our own **position manager** (monitors real
  quotes and submits the exit order when a level is crossed). This works for stocks, options, and
  crypto uniformly, and never depends on broker-specific bracket support. Native bracket may be
  added later for stocks/options as an optimization.

## Module map (new / changed)

| Concern | Module |
|---|---|
| Option contract discovery + option quotes | `backend/services/options_service.py` (new) |
| Crypto quotes/bars | `backend/services/crypto_service.py` (new) |
| Asset-class-aware payload + submit (OCC, mleg, crypto) | `backend/services/alpaca_service.py` |
| Asset-class-aware idempotent execution + TP/SL meta | `backend/services/order_execution.py` |
| Managed TP/SL exits (all asset classes, crypto 24/7) | `backend/services/position_manager.py` (new) |
| Options/crypto risk sizing + caps | `lumibot/custom_config/risk_engine.py` |
| Strategy entry point (place order) | `backend/services/asset_orders.py` `AssetOrderService.place_order` |
| UI reference + quick settings | `frontend/src/pages/Options.jsx`, `frontend/src/pages/Crypto.jsx` |

## Work items

- [x] 0. This plan/reference doc
- [x] 1. Order construction: payload + submit for options (single + multi-leg) and crypto
      (`alpaca_service._prepare_options_payload` / `_prepare_crypto_payload` / `_submit_mleg_to_alpaca_api`)
- [x] 2. Options service: contract discovery + latest quote (no fabrication) (`options_service.py`)
- [x] 3. Crypto data service: quotes/bars (no fabrication) (`crypto_service.py`)
- [x] 4. Risk sizing for options/crypto + kill-switch wiring (`risk_engine.max_order_notional`,
      premium/notional sizing in `asset_orders.py`)
- [x] 5. Execution: asset-class aware + TP/SL managed-exit metadata + idempotency (`asset_orders.py`)
- [x] 6. Position manager: fires TP/SL exits for options/crypto across sessions
      (`position_manager.py`, wired into `autonomous_runner.tick()` — runs even when closed for crypto)
- [x] 7. Strategy entry point: `AssetOrderService.place_order` (in-process). No manual order
      HTTP endpoints (removed) — bot trading is strategy-only.
- [x] 8. Frontend Options + Crypto pages: **reference + quick-settings only** (positions, order
      history, enable/paper/live toggles). No order entry. (`pages/Options.jsx`, `pages/Crypto.jsx`)
- [x] 9. Tests for all order/risk/execution/exit logic; full suite green
      (`tests/test_custom/test_options_crypto.py`)
- [x] 10. Docs + CHANGELOG + env/config keys

## What is NOT included (intentional)

- No autonomous options/crypto **strategy** yet (the user will define strategies later). The
  autonomous loop still trades stocks only; it also fires managed TP/SL exits for any option/crypto
  positions a strategy opens via `AssetOrderService`.
- **No manual trading in the bot** — no UI order ticket, no order-placement HTTP endpoint. Manual
  trading is done outside the bot (Alpaca directly). All bot trading is strategy-driven.
- No native broker bracket orders — TP/SL is managed in-app (`position_manager`) for cross-asset
  consistency (crypto cannot use native brackets).

## Safety

- Live options/crypto require explicit per-class enablement + (options) account approval, plus the
  global live gates. Defaults keep everything paper/simulation safe.
