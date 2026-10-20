# Stocks In Play ORB v1

`stocks_in_play_orb_v1` is the first fully wired strategy in the Alpaca-only app branch.

## Scope

- Asset class: `stocks`.
- Direction: long-only.
- Instruments: liquid US stocks/ETFs.
- Data: Alpaca minute bars, daily bars, quotes, and spread checks where credentials are configured.
- Execution: proposal-first; orders flow through risk checks and the Alpaca order workflow.

## Flow

```text
market snapshots / Alpaca bars
-> ORB signal engine
-> proposal
-> risk approval
-> order row
-> pending_broker_submission
-> paper_submitted or live_submitted
```

The strategy class never places live broker orders directly.

## Backtesting

The 5-minute opening range requires minute bars. Alpaca is the prepared data route for intraday ORB backtests. When Alpaca credentials are missing, the backend records a safe warning instead of fabricating intraday bars.

## Live Safety

Live execution remains blocked unless:

- `trading_mode: live`
- `live_trading_enabled: true`
- Alpaca credentials are present in environment variables
- stock asset-class gates pass
- risk engine approval passes

Live trading is disabled by default.

## Autonomous loop & extended hours (behavior)

When the autonomous loop is running, the strategy is driven on a wall-clock cadence across the
pre-market (04:00–09:30 ET), regular (09:30–16:00 ET), and after-hours (16:00–20:00 ET) sessions:

- **Order types are session-aware.** During regular hours the native stop/market order types are
  used. During pre/post-market (only when extended hours is enabled), entries and exits become
  **marketable limit** orders (`limit` + `time_in_force=day` + `extended_hours=true`), the only type
  Alpaca accepts outside regular hours.
- **Signals are regular-hours constructs.** The opening range, RVOL, VWAP, and spread filters are
  defined for regular hours. By default the loop only *manages existing positions* outside regular
  hours and does not open new positions; it never fabricates bars to manufacture an extended-hours
  signal.
- **Protective risk & kill switch.** Realized PnL feeds the daily-loss limit. The kill switch is
  protective — it halts new entries but still allows risk-reducing exits so the bot can get flat.
  The risk ledger resets on the ET session day.

The implementation design, module map, and configuration/env reference are documented separately in
the development reference: `docs/development/EXTENDED_HOURS_AUTONOMOUS_TRADING.md`.
