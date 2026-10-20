# Alpaca-Only Architecture

This branch uses Alpaca as the only broker and market data provider.

## Native Lumibot Components

- `lumibot.brokers.Alpaca`
- `lumibot.data_sources.alpaca_data.AlpacaData`
- `lumibot.backtesting.alpaca_backtesting.AlpacaBacktesting`
- `lumibot.tools.alpaca_helpers`

## App Services

- `backend/services/alpaca_service.py`
- `backend/services/broker_factory.py`
- `backend/services/data_provider_factory.py`

Routes call services. Services handle credential checks, status, payload preparation, and status mapping.

## Preservation

The prior implementation is preserved on `robinhood-mcp`. It is not an active runtime path on `alpaca-bot`.
