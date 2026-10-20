"""Tests for the risk engine and execution controls."""

import pytest

from lumibot.custom_config.risk_engine import RiskEngine


def _base_config(**overrides):
    cfg = {
        "active_broker": "alpaca",
        "active_data_provider": "alpaca",
        "default_asset_class": "stocks",
        "trading_mode": "live",
        "live_trading_enabled": True,
        "active_asset_classes": ["stocks", "options", "crypto"],
        "paper_trading": {"assigned_capital": None, "use_assigned_capital_limit": False},
        "stocks": {
            "enabled": True,
            "paper_enabled": True,
            "live_enabled": False,
            "sizing_mode": "notional",
            "max_order_notional": 100,
        },
        "options": {"enabled": True, "paper_enabled": False, "live_enabled": False, "require_explicit_enablement": True, "explicit_enablement": False},
        "crypto": {"enabled": True, "paper_enabled": False, "live_enabled": False, "require_explicit_enablement": True, "explicit_enablement": False},
        "watchlist": {"stocks": ["AAPL", "MSFT", "GOOGL"]},
        "risk_limits": {
            "max_dollars_per_trade": 100,
            "max_loss_per_trade": 25,
            "max_daily_loss": 200,
            "max_trades_per_day": 10,
            "max_open_positions": 5,
        },
    }
    cfg.update(overrides)
    return cfg


class TestLiveTradingDefault:
    def test_live_trading_disabled_by_default(self):
        cfg = _base_config(live_trading_enabled=False)
        engine = RiskEngine(cfg)
        approved, reason = engine.approve("AAPL", 50)
        assert not approved
        assert "live_trading_enabled" in reason


class TestRiskLimits:
    def test_exceeds_max_dollars_per_trade(self):
        engine = RiskEngine(_base_config())
        approved, reason = engine.approve("AAPL", 500)
        assert not approved
        assert "max_dollars_per_trade" in reason

    def test_within_dollar_limit(self):
        engine = RiskEngine(_base_config())
        approved, _ = engine.approve("AAPL", 50)
        assert approved

    def test_assigned_capital_limit(self):
        engine = RiskEngine(_base_config(
            paper_trading={"assigned_capital": 50, "use_assigned_capital_limit": True}
        ))
        approved, reason = engine.approve_proposal("AAPL", 60)
        assert not approved
        assert "assigned_capital" in reason

    def test_assigned_capital_enabled_without_value_uses_available_capital(self):
        engine = RiskEngine(_base_config(
            paper_trading={"assigned_capital": None, "use_assigned_capital_limit": True}
        ))
        approved, reason = engine.approve_proposal("AAPL", 10)
        assert approved
        assert reason == "approved"

    def test_stock_max_order_notional_limit(self):
        engine = RiskEngine(_base_config(
            stocks={**_base_config()["stocks"], "max_order_notional": 5}
        ))
        approved, reason = engine.approve_proposal("AAPL", 25)
        assert not approved
        assert "max_order_notional" in reason

    def test_daily_loss_limit_uses_assigned_capital_when_lower(self):
        engine = RiskEngine(_base_config(
            paper_trading={"assigned_capital": 50, "use_assigned_capital_limit": True},
            stocks={**_base_config()["stocks"], "max_order_notional": 100},
            risk_limits={**_base_config()["risk_limits"], "max_daily_loss": 200},
        ))
        engine.record_trade(loss=50)
        approved, reason = engine.approve_proposal("AAPL", 10)
        assert not approved
        assert "daily loss limit" in reason
        assert "50.0" in reason

    def test_daily_trade_limit(self):
        engine = RiskEngine(_base_config(
            risk_limits={**_base_config()["risk_limits"], "max_trades_per_day": 2}
        ))
        engine.record_trade()
        engine.record_trade()
        approved, reason = engine.approve("AAPL", 50)
        assert not approved
        assert "daily trade limit" in reason

    def test_daily_loss_limit(self):
        engine = RiskEngine(_base_config(
            risk_limits={**_base_config()["risk_limits"], "max_daily_loss": 50}
        ))
        engine.record_trade(loss=50)
        approved, reason = engine.approve("AAPL", 50)
        assert not approved
        assert "daily loss limit" in reason

    def test_max_open_positions(self):
        engine = RiskEngine(_base_config(
            risk_limits={**_base_config()["risk_limits"], "max_open_positions": 1}
        ))
        engine.set_open_positions(1)
        approved, reason = engine.approve("AAPL", 50)
        assert not approved
        assert "max open positions" in reason


class TestAssetClassBlocking:
    def test_unsupported_asset_class_rejected(self):
        engine = RiskEngine(_base_config())
        approved, reason = engine.approve("BTCUSD", 50, asset_class="crypto")
        assert not approved
        assert "requires explicit enablement" in reason

    def test_forex_rejected(self):
        engine = RiskEngine(_base_config())
        approved, reason = engine.approve("EURUSD", 50, asset_class="forex")
        assert not approved
        assert "not supported" in reason

    def test_stocks_allowed(self):
        engine = RiskEngine(_base_config())
        approved, _ = engine.approve("AAPL", 50, asset_class="stocks")
        assert approved


class TestExecutionRequiresRiskApproval:
    def test_symbol_not_in_watchlist(self):
        engine = RiskEngine(_base_config())
        approved, reason = engine.approve("XYZ", 50)
        assert not approved
        assert "watchlist" in reason

    def test_wrong_trading_mode(self):
        engine = RiskEngine(_base_config(trading_mode="simulation"))
        approved, reason = engine.approve("AAPL", 50)
        assert not approved
        assert "trading_mode" in reason
