# Migration validation — 2026-10-20

- Application tests: **254 passed** (`tests/test_custom`).
- Python installation and `pip check`: passed.
- Frontend installation and production build: passed.
- Frontend `npm audit`: **0 vulnerabilities** after compatible lockfile updates.
- API lifespan startup and `/api/health`: passed with a temporary SQLite database.
- Live trading: disabled; scheduler: disabled; paper order submission: mocked by default.
- Upstream broker/data backtests and external AI provider tests: not run; require external services.
- Gitleaks: zero findings in the sanitized export.

## Scope and safeguards

Gitleaks 8.30.1 was installed from the official release and its SHA-256 checked.
Source history and the sanitized export were scanned. Fresh Git history excludes old secrets.
Private exports, logs, local databases, deployment evidence, and generated artifacts are excluded.
Bandit found no high-severity findings in the audited application Python directories.
This is a migration audit, not a claim that the entire upstream framework is vulnerability-free.
No production services, customer data, deployments, banking transactions, or brokerage orders were used.

## Dependency advisories requiring scoped handling

`pip-audit` still reports NLTK 3.10.3 (`PYSEC-2026-3740`) and setuptools 80.10.2
(`PYSEC-2026-3447`). There is no NLTK fix listed; the affected model-file APIs are not
called by this application's backend or LumiBot source. Do not load untrusted NLTK model artifacts.
The setuptools advisory concerns Unicode normalization of source-distribution exclusions on macOS.
The migration publishes Git source, not an sdist, and packages no secrets. Do not build distributions
from a working directory containing credentials. The upstream setuptools<81 compatibility cap
is retained; upgrading it requires validating dependencies that still use pkg_resources.

All observed runtime advisories in aiohttp, LiteLLM, LangGraph, and Starlette were addressed.
The remaining scoped findings do not expose a reachable path in the validated local application.
The unauthenticated API is local-only; do not expose it to an untrusted network.

## Source selection and changes

The Alpaca branch preserves stock ORB automation, options/crypto manual rails, risk controls,
order execution, fill reconciliation, and the web UI. The earlier development and Robinhood MCP
branches use a different broker architecture and were not merged into the Alpaca runtime.
Session-date consistency and credential-free mocked-paper submission were repaired and tested.
Upstream GPLv3 licensing and Lumiwealth attribution were restored. The optional ThetaTerminal
JAR was excluded because redistribution rights were not established.
