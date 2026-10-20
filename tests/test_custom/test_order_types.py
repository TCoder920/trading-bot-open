"""Tests for the session-aware order-type decision layer (HARD BLOCKER #2)."""

import pytest

from lumibot.custom_strategies.order_types import (
    marketable_limit_price,
    resolve_order_type,
    session_allows_intent,
)
from lumibot.custom_strategies.session import Session


class TestRegularHours:
    def test_market_stays_market(self):
        spec = resolve_order_type(side="buy", session=Session.REGULAR, intent="market",
                                  reference_price=100.0)
        assert spec.order_type == "market"
        assert spec.extended_hours is False
        assert spec.time_in_force == "day"

    def test_stop_stays_stop(self):
        spec = resolve_order_type(side="buy", session=Session.REGULAR, intent="stop",
                                  reference_price=100.0, stop_price=101.0)
        assert spec.order_type == "stop"
        assert spec.stop_price == 101.0
        assert spec.extended_hours is False

    def test_stop_requires_stop_price(self):
        with pytest.raises(ValueError):
            resolve_order_type(side="buy", session=Session.REGULAR, intent="stop",
                               reference_price=100.0)


class TestExtendedHours:
    def test_market_intent_becomes_marketable_limit_buy(self):
        spec = resolve_order_type(side="buy", session=Session.PRE_MARKET, intent="market",
                                  reference_price=100.0,
                                  config={"marketable_limit_offset_pct": 0.5})
        assert spec.order_type == "limit"
        assert spec.time_in_force == "day"
        assert spec.extended_hours is True
        assert spec.limit_price == pytest.approx(100.5)  # 0.5% above
        assert spec.converted_from == "market"

    def test_stop_intent_becomes_marketable_limit(self):
        spec = resolve_order_type(side="buy", session=Session.AFTER_HOURS, intent="stop",
                                  reference_price=200.0, stop_price=201.0,
                                  config={"marketable_limit_offset_pct": 0.2})
        assert spec.order_type == "limit"
        assert spec.extended_hours is True
        assert spec.limit_price == pytest.approx(200.4)

    def test_sell_marketable_limit_is_below_reference(self):
        spec = resolve_order_type(side="sell", session=Session.AFTER_HOURS, intent="market",
                                  reference_price=100.0,
                                  config={"marketable_limit_offset_pct": 0.5})
        assert spec.limit_price == pytest.approx(99.5)
        assert spec.extended_hours is True

    def test_extended_requires_reference_price(self):
        with pytest.raises(ValueError):
            resolve_order_type(side="buy", session=Session.PRE_MARKET, intent="market",
                               reference_price=None)

    def test_explicit_limit_preserved_but_tagged(self):
        spec = resolve_order_type(side="buy", session=Session.PRE_MARKET, intent="limit",
                                  reference_price=100.0, limit_price=99.0)
        assert spec.order_type == "limit"
        assert spec.extended_hours is True
        assert spec.limit_price == 99.0


class TestMarketableLimitPrice:
    def test_buy_above(self):
        assert marketable_limit_price("buy", 100.0, offset_pct=1.0) == pytest.approx(101.0)

    def test_sell_below(self):
        assert marketable_limit_price("sell", 100.0, offset_pct=1.0) == pytest.approx(99.0)

    def test_rounds_to_tick(self):
        price = marketable_limit_price("buy", 100.013, offset_pct=0.0, tick_size=0.01)
        assert price == pytest.approx(100.01)


class TestSessionAllowsIntent:
    def test_closed_allows_nothing(self):
        assert not session_allows_intent(Session.CLOSED, "limit")

    def test_extended_only_limit(self):
        assert session_allows_intent(Session.PRE_MARKET, "limit")
        assert not session_allows_intent(Session.PRE_MARKET, "market")
        assert not session_allows_intent(Session.AFTER_HOURS, "stop")

    def test_regular_allows_all(self):
        assert session_allows_intent(Session.REGULAR, "market")
        assert session_allows_intent(Session.REGULAR, "stop")
