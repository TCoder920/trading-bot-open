# Alpaca Setup

## Environment Variables

Set credentials in the repo-local ignored file:

[.env](/path/to/workspace/Public/trading-bot2/.env)

```dotenv
TRADING_MODE=paper
ALPACA_API_KEY="paper_key"
ALPACA_API_SECRET="paper_secret"
ALPACA_OAUTH_TOKEN=
ALPACA_IS_PAPER=true
ALPACA_DATA_FEED=iex
ALPACA_MOCK_PAPER_SUBMISSION=false
ALPACA_PAPER_API_KEY="paper_key"
ALPACA_PAPER_API_SECRET="paper_secret"
ALPACA_LIVE_API_KEY="live_key"
ALPACA_LIVE_API_SECRET="live_secret"
LIVE_TRADING_ENABLED=false
OPTIONS_PAPER_ENABLED=true
OPTIONS_EXPLICIT_ENABLEMENT=true
OPTIONS_LIVE_ENABLED=false
OPTIONS_ACCOUNT_APPROVED=false
OPTIONS_APPROVAL_STATUS=pending
CRYPTO_LIVE_ENABLED=false
```

Optional OAuth:

```dotenv
ALPACA_OAUTH_TOKEN="token"
```

Do not store credentials in YAML, SQLite, frontend files, tracked files, or docs.

OAuth is not required for this bot when using your own Alpaca API key and secret.

## Modes

- `simulation`: no broker credentials required. Orders are always mocked locally.
- `paper`: requires Alpaca credentials before broker-connected paper trades.
- `live`: requires credentials, `trading_mode: live`, and `live_trading_enabled: true`.

Live trading is disabled by default.

## Mock paper submission (`ALPACA_MOCK_PAPER_SUBMISSION` / `alpaca.mock_paper_submission`)

Controls whether paper orders are actually sent to Alpaca:

- Default is `false` — paper mode submits real orders to your Alpaca **paper** account.
- It is editable in the Settings UI (Alpaca → "Mock Paper Submission").
- The mock path exists only for AI development agents, so automated development tasks never place
  real paper orders. Set `ALPACA_MOCK_PAPER_SUBMISSION=true` while developing. The env var overrides
  the saved UI/config value.

This flag only affects `paper` mode. `simulation` is always mocked; `live` submission is separately
gated by `live_trading_enabled` + `trading_mode: live`.
