# Architecture

## Branch Shape

`alpaca-bot` is Alpaca-only. The preserved prior implementation lives on `robinhood-mcp`.

## Components

```text
React/Vite UI
  -> FastAPI routes
  -> service layer
  -> Lumibot native Alpaca broker/data/backtesting
  -> SQLite persistence
```

## Backend Routes

- `/api/alpaca/*`: broker, credentials, account, positions, orders, and data status.
- `/api/assets/*`: asset-class readiness for stocks, options, and crypto.
- `/api/orders/*`: proposal, risk approval, review, broker submission, status updates.
- `/api/orb/*`: stock ORB runtime, proposals, diagnostics, promotion.
- `/api/backtests/*`: Lumibot backtesting, routed to Alpaca where credentials are available.
- `/api/datasources`: Alpaca data provider capability surface.

## Persistence

Active generic tables:

- `orders`
- `trades`
- `positions`
- `logs`
- `strategies`
- `watchlist_items`
- `backtests`
- `daily_ledger`
- `config_history`
- `orb_proposals`
- `orb_runtime_state`

Generic Alpaca order fields include `broker`, `broker_order_id`, `asset_class`, `paper`, `client_order_id`, `strategy_id`, `risk_status`, `execution_status`, and asset-class-specific option/crypto fields.

Existing old local SQLite files may contain obsolete tables or columns. Active code does not read or write them.

## Order Flow

```text
proposal
-> risk check
-> risk_approved
-> pending_broker_submission
-> paper_submitted or live_submitted
-> accepted / paper_filled / live_filled / partially_filled / canceled / rejected / failed
```

## Lumibot Native Components

- `lumibot.brokers.Alpaca`
- `lumibot.data_sources.alpaca_data.AlpacaData`
- `lumibot.backtesting.alpaca_backtesting.AlpacaBacktesting`
- `lumibot.tools.alpaca_helpers`
