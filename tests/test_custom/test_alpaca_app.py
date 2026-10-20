"""Tests for the Alpaca-only app service layer."""

from backend.services.alpaca_service import AlpacaService


def _base_config(**overrides):
    cfg = {
        "active_broker": "alpaca",
        "active_data_provider": "alpaca",
        "trading_mode": "simulation",
        "live_trading_enabled": False,
        "default_asset_class": "stocks",
        "active_asset_classes": ["stocks", "options", "crypto"],
        "alpaca": {
            "enabled": True,
            "paper": True,
            "data_enabled": True,
            "execution_enabled": True,
            "require_env_credentials": True,
            "api_key_env_var": "ALPACA_API_KEY",
            "api_secret_env_var": "ALPACA_API_SECRET",
            "oauth_token_env_var": "ALPACA_OAUTH_TOKEN",
            "is_paper_env_var": "ALPACA_IS_PAPER",
            "mock_paper_submission": True,
        },
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "stocks": {
            "enabled": True,
            "paper_enabled": True,
            "live_enabled": False,
            "sizing_mode": "notional",
            "min_order_notional": 1,
            "max_order_notional": None,
        },
        "options": {
            "enabled": True,
            "paper_enabled": True,
            "live_enabled": False,
            "require_explicit_enablement": True,
            "explicit_enablement": True,
            "approval_status": "pending",
            "account_approved": False,
        },
        "crypto": {
            "enabled": True,
            "paper_enabled": False,
            "live_enabled": False,
            "require_explicit_enablement": True,
            "explicit_enablement": False,
        },
    }
    cfg.update(overrides)
    return cfg


def test_broker_factory_status_alpaca_ready_shape():
    service = AlpacaService(_base_config())
    status = service.broker_status()
    assert status["broker"] == "alpaca"
    assert status["native_lumibot"]["broker"] == "lumibot.brokers.Alpaca"


def test_credential_detection_missing(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_OAUTH_TOKEN", raising=False)
    creds = AlpacaService(_base_config()).credential_status()
    assert creds["configured"] is False


def test_credential_detection_key_secret(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    monkeypatch.delenv("ALPACA_OAUTH_TOKEN", raising=False)
    creds = AlpacaService(_base_config()).credential_status()
    assert creds["configured"] is True


def test_order_status_mapping():
    service = AlpacaService(_base_config())
    assert service.map_order_status("filled", paper=True) == "paper_filled"
    assert service.map_order_status("filled", paper=False) == "live_filled"
    assert service.map_order_status("partially_filled") == "partially_filled"


def test_simulation_submission_local_only():
    service = AlpacaService(_base_config())
    result = service.submit_order({"id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks"})
    assert result["execution_status"] == "accepted"
    assert result["details"]["local_only"] is True


def test_paper_submission_mocked(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    cfg = _base_config(trading_mode="paper")
    service = AlpacaService(cfg)
    result = service.submit_order({
        "id": 1,
        "symbol": "AAPL",
        "side": "buy",
        "asset_class": "stocks",
        "sizing_mode": "notional",
        "notional": 5,
    })
    assert result["execution_status"] == "paper_submitted"
    assert result["details"]["mocked"] is True
    assert result["details"]["payload"]["notional"] == 5
    assert "qty" not in result["details"]["payload"]


def test_stock_notional_payload_uses_day_and_no_qty():
    service = AlpacaService(_base_config())
    payload = service.prepare_order_payload({
        "id": 1,
        "symbol": "MSFT",
        "side": "buy",
        "asset_class": "stocks",
        "sizing_mode": "notional",
        "notional": 10,
        "quantity": None,
        "time_in_force": "gtc",
    })
    assert payload["notional"] == 10
    assert payload["time_in_force"] == "day"
    assert "qty" not in payload


def test_stock_whole_share_payload_uses_qty_and_no_notional():
    service = AlpacaService(_base_config())
    payload = service.prepare_order_payload({
        "id": 1,
        "symbol": "MSFT",
        "side": "buy",
        "asset_class": "stocks",
        "sizing_mode": "whole_share",
        "quantity": 1,
        "dollar_amount": 150,
    })
    assert payload["qty"] == 1
    assert "notional" not in payload


def test_order_payload_rejects_qty_and_notional_together():
    service = AlpacaService(_base_config())
    try:
        service.prepare_order_payload({
            "id": 1,
            "symbol": "MSFT",
            "side": "buy",
            "asset_class": "stocks",
            "quantity": 1,
            "notional": 10,
        })
    except ValueError as exc:
        assert "both quantity and notional" in str(exc)
    else:
        raise AssertionError("expected mixed sizing payload to fail")


def test_mock_asset_metadata_fractionable():
    service = AlpacaService(_base_config())
    assert service.asset_metadata("MSFT")["fractionable"] is True
    assert service.asset_metadata("NOFRAC")["fractionable"] is False


def test_paper_submission_calls_alpaca_api_when_mock_disabled(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_API_SECRET", "secret")
    cfg = _base_config(trading_mode="paper")
    cfg["alpaca"]["mock_paper_submission"] = False
    service = AlpacaService(cfg)
    calls = []

    class FakeApi:
        def submit_order(self, order_data):
            calls.append(order_data)
            return SimpleNamespace(id="alpaca-order-1", status="accepted", client_order_id=order_data.client_order_id)

    monkeypatch.setattr(service, "_build_broker", lambda: SimpleNamespace(api=FakeApi()))
    result = service.submit_order({"id": 1, "symbol": "AAPL", "side": "buy", "asset_class": "stocks", "quantity": 1})

    assert result["execution_status"] == "paper_submitted"
    assert result["broker_order_id"] == "alpaca-order-1"
    assert result["details"]["mocked"] is False
    assert calls


def test_mock_paper_submission_defaults_to_false():
    # Real Alpaca PAPER submission is the human default; mock is opt-in for AI dev agents.
    from lumibot.custom_config.settings import _normalize_alpaca_only_config

    cfg = _normalize_alpaca_only_config({})
    assert cfg["alpaca"]["mock_paper_submission"] is False


def test_paper_uses_real_path_when_mock_disabled_requires_credentials(monkeypatch):
    for var in (
        "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_OAUTH_TOKEN",
        "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET",
        "ALPACA_LIVE_API_KEY", "ALPACA_LIVE_API_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = _base_config(trading_mode="paper")
    cfg["alpaca"]["mock_paper_submission"] = False
    service = AlpacaService(cfg)
    result = service.submit_order({"id": 1, "symbol": "AAPL", "side": "buy",
                                   "asset_class": "stocks", "quantity": 1})
    # Real path taken (not mocked) -> requires credentials, so it fails cleanly here.
    assert result["execution_status"] == "failed"
    assert "credentials" in result["errors"][0].lower()


def test_no_active_robinhood_references_in_app_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    targets = [
        root / "backend",
        root / "frontend" / "src",
        root / "lumibot" / "custom_config",
        root / "lumibot" / "custom_strategies",
    ]
    banned = [
        "Robinhood",
        "robinhood",
        "robinhood_mcp",
        "pending_agent_execution",
        "pending_agent_review",
        "selected_agentic_account",
    ]
    offenders = []
    for target in targets:
        for path in target.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".jsx", ".js", ".yaml"}:
                text = path.read_text(errors="ignore")
                if any(term in text for term in banned):
                    offenders.append(str(path.relative_to(root)))
    assert offenders == []
