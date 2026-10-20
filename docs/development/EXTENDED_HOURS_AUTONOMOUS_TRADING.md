# Extended-Hours Autonomous Trading — Production Readiness Plan

One-line description: Implementation plan + tracker for making trading-bot2 autonomously trade
the `stocks_in_play_orb_v1` strategy on Alpaca PAPER across pre-market, regular, and after-hours
sessions, with correct order types, managed exits, fill reconciliation, and a working kill switch.

- Last Updated: 2026-06-15
- Status: Complete (autonomous extended-hours trading on Alpaca PAPER)
- Audience: Engineers / AI agents working on trading-bot2 (Alpaca-only branch `alpaca-bot`)

## Overview

The strategy layer is clock-aware but the bot was not production-ready for autonomous
live/paper trading. This change set adds a real wall-clock scheduler, extended-hours-aware order
execution (Alpaca only accepts marketable `limit` + `time_in_force=day` + `extended_hours=true`
in pre/post-market), a real (but safely gated) Alpaca PAPER submission path, fill reconciliation
that feeds realized PnL into the daily-loss kill switch, crash-safe state persistence, and an ET
session-day risk ledger.

### Hard invariants (do not violate)

- **No fabricated market data.** Missing bars/quotes surface as empty + explicit warning. This
  applies to thin extended-hours data too: real gaps stay gaps.
- Alpaca is the only broker and only data provider.
- `live_trading_enabled=false` and `trading_mode=simulation` by default. No real live trades.
  Real submission is validated against Alpaca PAPER only.
- Simulation stays fully mocked. Live stays disabled by default.
- Frontend stays black/white/grayscale.

### Alpaca extended-hours facts (confirmed from current Alpaca docs, 2026-06)

- Extended-hours-eligible orders MUST be `limit` orders with `time_in_force=day` and
  `extended_hours=true`. Market/stop/stop-limit orders are rejected outside RTH.
- Sessions (ET): pre-market 04:00–09:30, regular 09:30–16:00, after-hours 16:00–20:00.
  (Overnight 20:00–04:00 exists but is out of scope; this bot trades pre/RTH/post only.)
- The `iex` data feed is sparse outside RTH; `sip` provides full pre/post-market data.
- Extended-hours limit orders fill immediately if marketable, so entries/exits are converted to
  **marketable limit** orders (limit price offset past the touch by a configurable amount).

## Work items

- [x] 0. Plan doc (this file)
- [x] 1. Real-time scheduler / autonomous loop
  - [x] `SessionClock` single ET time source (`lumibot/custom_strategies/session.py`)
  - [x] Background `TradingScheduler` thread + `AutonomousRunner.tick()`
  - [x] Wire `/api/bot/start|pause|resume|stop` to actually control the loop
  - [x] Missed-tick / catch-up handling on restart
- [x] 2. Extended-hours-aware execution (HARD BLOCKER)
  - [x] `extended_hours` plumbed through `prepare_order_payload` + `_submit_to_alpaca_api`
  - [x] Order-type decision layer (`order_types.py`): session → correct Alpaca order type
  - [x] Stop/market intents → marketable limit in pre/post-market; RTH unchanged
  - [x] Config flags + validation
- [x] 3. Real order submission (gated; PAPER-validated, live disabled by default)
- [x] 4. Order lifecycle / fill reconciliation (polling) persisted in SQLite
- [x] 5. Exit / position management (stop, partial-at-R, flatten) extended-hours aware
- [x] 6. State persistence & crash recovery (engine per-symbol state + ledger)
- [x] 7. Risk ledger ET session-day boundary + fills → realized PnL → kill switch
- [x] 8. Extended-hours market data (SIP feed) + RTH-only signal gating, no fabrication
- [x] 9. Idempotency & concurrency safety
- [x] 10. Observability, alerting, hard kill switch surfaced in status/UI
- [x] 11. Tests for all new logic; full `tests/test_custom/` suite green
- [x] 12. Docs (`docs/`, `docsrc/`, `ENV_VARS`) + `CHANGELOG.md`

## Module map

| Concern | Module |
|---|---|
| Single ET time source + session classification | `lumibot/custom_strategies/session.py` |
| Order-type decision (RTH vs extended hours) | `lumibot/custom_strategies/order_types.py` |
| Autonomous loop orchestration | `backend/services/autonomous_runner.py` |
| Background wall-clock scheduler thread | `backend/services/scheduler.py` |
| Alpaca market-data snapshots (no fabrication) | `backend/services/market_data.py` |
| Idempotent order submission + persistence | `backend/services/order_execution.py` |
| Fills → trades → realized PnL → ledger | `backend/services/fill_reconciler.py` |
| Extended-hours payload plumbing | `backend/services/alpaca_service.py` |
| ET session-day ledger + kill switch | `lumibot/custom_config/risk_engine.py` |

## Session-day boundary (definition)

The risk "trading day" is the **ET calendar date of the active session**. The pre-market session
(04:00 ET) through the after-hours session (20:00 ET) of the same ET date belong to one trading
day. The daily ledger (trade count, realized loss) resets when the ET date changes, evaluated via
`SessionClock.session_day()`. Overnight (20:00–04:00) is out of scope and treated as closed.

## New environment variables / config

See `docs/ENV_VARS.md` and `docsrc/environment_variables.rst`. Summary:

- `alpaca.allow_extended_hours` (config) — enable pre/post-market trading. Default `false`.
- `alpaca.extended_hours_data_feed` (config) — feed used outside RTH (`sip`). Default `sip`.
- `alpaca.marketable_limit_offset_pct` (config) — how far past the touch to place marketable
  limits in extended hours. Default `0.2` (%).
- `stocks_in_play_orb_v1.premarket_session_start/end`, `postmarket_session_start/end` — ET windows.
- `stocks_in_play_orb_v1.extended_hours_signals` — `rth_only` (default) gates ORB signals to RTH.
- `ALPACA_ALLOW_EXTENDED_HOURS`, `ALPACA_EXTENDED_HOURS_DATA_FEED`, `TRADING_SCHEDULER_ENABLED`,
  `TRADING_SCHEDULER_INTERVAL_SECONDS` — env overrides.

## Post-plan refinements (2026-06-15)

- **Protective kill switch.** The kill switch halts NEW exposure (entries/buys) but never blocks
  risk-reducing exits (sells/flatten), so the bot can always get flat. Exits flow through
  `RiskEngine.approve_exit` (not the entry-oriented `approve_proposal`), so the daily-loss limit,
  per-trade caps, watchlist, and kill switch do not block an exit. The entry gate is
  `RiskEngine.allows_new_entries`. See `backend/services/order_execution.py` and
  `lumibot/custom_config/risk_engine.py`.
- **Paper submission default flipped to real.** `alpaca.mock_paper_submission` now defaults to
  `false` so the human-operated app submits real Alpaca PAPER orders. The mock path is for AI
  development agents only — set `ALPACA_MOCK_PAPER_SUBMISSION=true` (env overrides config/UI) so
  development tasks never place real paper orders. The flag is editable from the Settings UI
  (Alpaca → "Mock Paper Submission"). Simulation stays fully mocked regardless; live remains gated
  by `live_trading_enabled` + `trading_mode=live`.
- **Documentation layout.** This development reference moved from `docs/` root to `docs/development/`
  to keep development docs separate from strategy/library docs.
