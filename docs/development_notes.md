# Development Notes

## Active Branch

- `alpaca-bot`: Alpaca-only app branch.
- Prior implementation is preserved on `robinhood-mcp`.

## Defaults

- `active_broker: alpaca`
- `active_data_provider: alpaca`
- `trading_mode: simulation`
- `live_trading_enabled: false`
- `default_asset_class: stocks`
- `active_asset_classes: [stocks, options, crypto]`

## Reference docs (development)

Engineering / development documentation for this app lives under `docs/development/`, kept
separate from strategy and library documentation:

- `docs/development/EXTENDED_HOURS_AUTONOMOUS_TRADING.md` — autonomous extended-hours trading:
  implementation plan, module map (created/modified/removed), session-day boundary, and the
  full config/env reference.

## Service Boundaries

- Routes must call `backend/services/*`.
- Routes must not construct Alpaca broker/data clients directly.
- Credentials must be read from environment variables only.
- Paper submission is real by default (`alpaca.mock_paper_submission: false`) and is controllable
  from the Settings UI. The mock path exists only for AI development agents: set
  `ALPACA_MOCK_PAPER_SUBMISSION=true` (or toggle it in the UI) so development tasks never place
  real paper orders. The env var overrides the saved UI/config value.

## Testing

Run:

```bash
.venv/bin/python -m pytest tests/test_custom/ -v
```

Frontend:

```bash
cd frontend
npm run build
```

## Safety Rules

- Do not place trades.
- Do not attempt live trading.
- Do not store credentials.
- Keep stock ORB stock-only.
- Keep options and crypto scaffolded until separately implemented and tested.
