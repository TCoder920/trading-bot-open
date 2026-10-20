# Trading Bot Open

An Alpaca-focused trading research application built on LumiBot, with a FastAPI API, React interface, risk controls, and strategy automation.

Collaborative development is welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Local development

Use Python 3.12 and Node.js 22.21 or newer. Start from a fresh clone with no production credentials.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Simulation is the default; paper submission is mocked by default. Live trading and the scheduler are disabled. No credentials are needed for the local application. The API has no multi-user authentication: bind to loopback only. Real broker/data integrations and upstream credential-dependent backtests are outside the default test workflow.

In another terminal, install and start the web interface:

```sh
cd frontend
npm ci --ignore-scripts
npm run dev -- --host 127.0.0.1
```

## Validation

```sh
python scripts/run_tests.py
(cd frontend && npm ci --ignore-scripts && npm run build)
```

See [VALIDATION.md](VALIDATION.md) for actual results, security findings, and unsupported integration tests.
CI uses synthetic settings and never deploys an application.

## License and source

GPL-3.0-only. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
Third-party components retain their own licenses. Modified deployments must preserve applicable
license notices and source-access obligations. The source is https://github.com/TCoder920/trading-bot-open.

## Security

See [SECURITY.md](SECURITY.md). Do not commit secrets, databases, logs, exports, or real user records.
