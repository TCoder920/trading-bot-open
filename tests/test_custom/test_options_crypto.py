"""Tests for options & crypto trading rails: payload construction, request building,
asset-order submission (idempotency, risk, protective kill switch), and managed TP/SL exits.
"""

import tempfile

import pytest

import backend.database as db


@pytest.fixture(autouse=True)
def temp_db():
    prev = db.DB_PATH
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db.DB_PATH = type(prev)(tmp.name)
    db.init_db()
    yield
    db.DB_PATH = prev


from backend.services.alpaca_service import AlpacaService  # noqa: E402
from backend.services.asset_orders import AssetOrderService  # noqa: E402
from backend.services.position_manager import PositionManager  # noqa: E402
from lumibot.custom_config.risk_engine import RiskEngine  # noqa: E402


def _cfg(**overrides):
    cfg = {
        "active_broker": "alpaca", "active_data_provider": "alpaca",
        "trading_mode": "paper", "live_trading_enabled": False,
        "active_asset_classes": ["stocks", "options", "crypto"],
        "alpaca": {"enabled": True, "mock_paper_submission": True},
        "options": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                    "explicit_enablement": True, "account_approved": True,
                    "max_order_notional": 1_000_000},
        "crypto": {"enabled": True, "paper_enabled": True, "live_enabled": False,
                   "explicit_enablement": True, "max_order_notional": 1_000_000},
        "risk_limits": {"max_dollars_per_trade": 1_000_000, "max_loss_per_trade": 100000,
                        "max_daily_loss": 1_000_000, "max_trades_per_day": 1000,
                        "max_open_positions": 1000},
    }
    cfg.update(overrides)
    return cfg


# ── Payload construction (pure) ─────────────────────────────────────────────
class TestOptionsPayload:
    def test_single_leg_market(self):
        svc = AlpacaService(_cfg())
        p = svc.prepare_order_payload({
            "id": 1, "asset_class": "options", "symbol": "AAPL250117C00150000",
            "side": "buy", "quantity": 2, "order_type": "market",
        })
        assert p["asset_class"] == "options"
        assert p["symbol"] == "AAPL250117C00150000"
        assert p["qty"] == 2
        assert p["time_in_force"] == "day"
        assert "extended_hours" not in p  # options never trade extended hours

    def test_limit_requires_price(self):
        svc = AlpacaService(_cfg())
        with pytest.raises(ValueError):
            svc.prepare_order_payload({
                "id": 1, "asset_class": "options", "symbol": "AAPL250117C00150000",
                "side": "buy", "quantity": 1, "order_type": "limit",
            })

    def test_stop_intent_downgraded_to_limit(self):
        svc = AlpacaService(_cfg())
        p = svc.prepare_order_payload({
            "id": 1, "asset_class": "options", "symbol": "AAPL250117C00150000",
            "side": "sell", "quantity": 1, "order_type": "stop", "limit_price": 1.25,
        })
        assert p["type"] == "limit"
        assert p["limit_price"] == 1.25

    def test_multileg_payload(self):
        svc = AlpacaService(_cfg())
        p = svc.prepare_order_payload({
            "id": 5, "asset_class": "options", "symbol": "AAPL250117C00150000",
            "side": "buy", "quantity": 1, "order_type": "limit", "limit_price": 0.5,
            "legs": [
                {"symbol": "AAPL250117C00150000", "side": "buy", "ratio_qty": 1},
                {"symbol": "AAPL250117C00160000", "side": "sell", "ratio_qty": 1},
            ],
        })
        assert p["order_class"] == "mleg"
        assert len(p["legs"]) == 2
        assert p["legs"][1]["side"] == "sell"
        assert p["limit_price"] == 0.5


class TestCryptoPayload:
    def test_market_notional(self):
        svc = AlpacaService(_cfg())
        p = svc.prepare_order_payload({
            "id": 1, "asset_class": "crypto", "symbol": "BTC/USD", "side": "buy",
            "notional": 100.0, "order_type": "market",
        })
        assert p["symbol"] == "BTC/USD"
        assert p["notional"] == 100.0
        assert p["time_in_force"] == "gtc"
        assert "extended_hours" not in p

    def test_day_tif_converted_to_gtc(self):
        svc = AlpacaService(_cfg())
        p = svc.prepare_order_payload({
            "id": 1, "asset_class": "crypto", "symbol": "ETH/USD", "side": "buy",
            "quantity": 0.5, "order_type": "market", "time_in_force": "day",
        })
        assert p["time_in_force"] == "gtc"
        assert p["qty"] == 0.5

    def test_notional_must_be_market(self):
        svc = AlpacaService(_cfg())
        with pytest.raises(ValueError):
            svc.prepare_order_payload({
                "id": 1, "asset_class": "crypto", "symbol": "BTC/USD", "side": "buy",
                "notional": 100.0, "order_type": "limit", "limit_price": 50000,
            })

    def test_stop_limit_requires_both(self):
        svc = AlpacaService(_cfg())
        with pytest.raises(ValueError):
            svc.prepare_order_payload({
                "id": 1, "asset_class": "crypto", "symbol": "BTC/USD", "side": "sell",
                "quantity": 0.1, "order_type": "stop_limit", "limit_price": 50000,
            })


# ── Request building against the real SDK request classes ──────────────────
class _FakeApi:
    def __init__(self):
        self.captured = None

    def submit_order(self, order_data=None):
        self.captured = order_data
        return {"id": "broker-1", "status": "accepted", "client_order_id": getattr(order_data, "client_order_id", None)}


class _FakeBrokerWrap:
    def __init__(self, api):
        self.api = api


class TestRequestBuilding:
    def _svc_with_api(self):
        api = _FakeApi()
        svc = AlpacaService(_cfg())
        svc._build_broker = lambda: _FakeBrokerWrap(api)  # type: ignore[assignment]
        return svc, api

    def test_option_limit_request(self):
        from alpaca.trading.requests import LimitOrderRequest

        svc, api = self._svc_with_api()
        svc._submit_to_alpaca_api({
            "asset_class": "options", "symbol": "AAPL250117C00150000", "side": "buy",
            "type": "limit", "time_in_force": "day", "qty": 1, "limit_price": 1.5,
            "client_order_id": "coid-1",
        })
        assert isinstance(api.captured, LimitOrderRequest)
        assert api.captured.symbol == "AAPL250117C00150000"
        assert api.captured.extended_hours in (None, False)

    def test_mleg_request(self):
        from alpaca.trading.enums import OrderClass
        from alpaca.trading.requests import MarketOrderRequest

        svc, api = self._svc_with_api()
        svc._submit_to_alpaca_api({
            "asset_class": "options", "order_class": "mleg", "type": "market",
            "time_in_force": "day", "qty": 1, "client_order_id": "coid-mleg",
            "legs": [
                {"symbol": "AAPL250117C00150000", "side": "buy", "ratio_qty": 1},
                {"symbol": "AAPL250117C00160000", "side": "sell", "ratio_qty": 1},
            ],
        })
        assert isinstance(api.captured, MarketOrderRequest)
        assert api.captured.order_class == OrderClass.MLEG
        assert len(api.captured.legs) == 2

    def test_crypto_market_request(self):
        from alpaca.trading.requests import MarketOrderRequest

        svc, api = self._svc_with_api()
        svc._submit_to_alpaca_api({
            "asset_class": "crypto", "symbol": "BTC/USD", "side": "buy",
            "type": "market", "time_in_force": "gtc", "notional": 100.0,
            "client_order_id": "coid-c",
        })
        assert isinstance(api.captured, MarketOrderRequest)
        assert api.captured.symbol == "BTC/USD"
        assert float(api.captured.notional) == 100.0


# ── Asset-order submission ─────────────────────────────────────────────────
class _FakeBroker:
    def __init__(self):
        self.orders = []

    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "paper_submitted", "execution_status": "paper_submitted",
                "broker_order_id": f"paper-{len(self.orders)}",
                "client_order_id": order.get("client_order_id"), "paper": True,
                "details": {"payload": order}}


class TestAssetOrderService:
    def test_option_buy_submits_and_persists(self):
        broker = _FakeBroker()
        svc = AssetOrderService(_cfg(), broker=broker)
        res = svc.place_order(asset_class="options", symbol="AAPL250117C00150000",
                              option_symbol="AAPL250117C00150000", side="buy", quantity=2,
                              order_type="limit", limit_price=1.5, premium=1.5,
                              take_profit=3.0, stop_loss=0.75)
        assert res.status == "paper_submitted"
        order = db.get_order(res.order_id)
        assert order["asset_class"] == "options"
        assert order["metadata"]["take_profit"] == 3.0
        assert order["metadata"]["stop_loss"] == 0.75
        assert len(broker.orders) == 1

    def test_idempotent_duplicate(self):
        broker = _FakeBroker()
        svc = AssetOrderService(_cfg(), broker=broker)
        kw = dict(asset_class="crypto", symbol="BTC/USD", side="buy", notional=100.0,
                  order_type="market", client_order_id="fixed-coid")
        first = svc.place_order(**kw)
        second = svc.place_order(**kw)
        assert first.status == "paper_submitted"
        assert second.status == "duplicate"
        assert second.idempotent is True
        assert len(broker.orders) == 1  # not double-submitted

    def test_kill_switch_blocks_buy_allows_sell(self):
        broker = _FakeBroker()
        risk = RiskEngine(_cfg())
        risk.engage_kill_switch("DAILY_LOSS_BREACHED")
        svc = AssetOrderService(_cfg(), broker=broker, risk=risk)
        buy = svc.place_order(asset_class="crypto", symbol="BTC/USD", side="buy", notional=50.0)
        assert buy.status == "blocked"
        sell = svc.place_order(asset_class="crypto", symbol="BTC/USD", side="sell", quantity=0.1,
                               order_type="market")
        assert sell.status == "paper_submitted"  # protective: exits always allowed


# ── Managed TP/SL exits ────────────────────────────────────────────────────
class _FakeQuoteService:
    def __init__(self, price):
        self.price = price

    def latest_quote(self, symbol):
        return {"symbol": symbol, "bid": self.price, "ask": self.price, "mid": self.price}


class TestPositionManager:
    def _seed_entry(self, broker, asset_class, symbol, tp=None, sl=None):
        svc = AssetOrderService(_cfg(), broker=broker)
        res = svc.place_order(asset_class=asset_class, symbol=symbol, option_symbol=symbol if asset_class == "options" else None,
                              side="buy", quantity=1, order_type="market", take_profit=tp, stop_loss=sl)
        # Mark the entry as filled so the position manager picks it up.
        db.update_order(res.order_id, execution_status="paper_filled")
        return res

    def test_target_hit_submits_exit(self):
        broker = _FakeBroker()
        self._seed_entry(broker, "crypto", "BTC/USD", tp=110.0, sl=80.0)
        pm = PositionManager(_cfg(), asset_orders=AssetOrderService(_cfg(), broker=broker),
                             crypto=_FakeQuoteService(120.0), options=_FakeQuoteService(120.0))
        result = pm.manage()
        assert result.checked == 1
        assert len(result.exits) == 1
        assert result.exits[0]["reason"] == "target"
        # Idempotent: a second manage does not submit a duplicate exit.
        result2 = pm.manage()
        assert len(result2.exits) == 0

    def test_stop_hit_submits_exit(self):
        broker = _FakeBroker()
        self._seed_entry(broker, "options", "AAPL250117C00150000", tp=5.0, sl=1.0)
        pm = PositionManager(_cfg(), asset_orders=AssetOrderService(_cfg(), broker=broker),
                             crypto=_FakeQuoteService(0.5), options=_FakeQuoteService(0.5))
        result = pm.manage()
        assert len(result.exits) == 1
        assert result.exits[0]["reason"] == "stop"

    def test_no_quote_no_action(self):
        broker = _FakeBroker()
        self._seed_entry(broker, "crypto", "ETH/USD", tp=100.0, sl=50.0)

        class _NoQuote:
            def latest_quote(self, symbol):
                return {"symbol": symbol, "bid": None, "ask": None, "mid": None,
                        "warning": "no quote"}

        pm = PositionManager(_cfg(), asset_orders=AssetOrderService(_cfg(), broker=broker),
                             crypto=_NoQuote(), options=_NoQuote())
        result = pm.manage()
        assert result.checked == 1
        assert result.exits == []  # honest: no real quote -> no action
