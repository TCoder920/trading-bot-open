"""Alpaca broker and data service wrappers.

Credentials are read only from environment variables. Routes use this service
instead of constructing Lumibot broker/data classes directly.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from backend.config_validation import alpaca_credential_status, validate_trading_mode

MOCK_ASSETS = {
    "AAPL": {"symbol": "AAPL", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": True},
    "MSFT": {"symbol": "MSFT", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": True},
    "GOOGL": {"symbol": "GOOGL", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": True},
    "AMZN": {"symbol": "AMZN", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": True},
    "TSLA": {"symbol": "TSLA", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": True},
    "NOFRAC": {"symbol": "NOFRAC", "asset_class": "us_equity", "tradable": True, "status": "active", "fractionable": False},
}


@dataclass
class AlpacaService:
    cfg: dict

    def credential_status(self) -> dict:
        status = alpaca_credential_status(self.cfg)
        selected = self._selected_credentials()
        status.update({
            "configured": bool(selected["api_key"] and selected["api_secret"]) or bool(selected["oauth_token"]),
            "selected_mode": self.cfg.get("trading_mode", "simulation"),
            "selected_key_present": bool(selected["api_key"]),
            "selected_secret_present": bool(selected["api_secret"]),
            "selected_oauth_present": bool(selected["oauth_token"]),
        })
        return status

    def lumibot_config(self, *, paper: bool | None = None) -> dict:
        alpaca = self.cfg.get("alpaca", {})
        paper_value = self._paper_mode() if paper is None else paper
        selected = self._selected_credentials()
        return {
            "API_KEY": selected["api_key"],
            "API_SECRET": selected["api_secret"],
            "OAUTH_TOKEN": selected["oauth_token"],
            "PAPER": paper_value,
            "MARKET": alpaca.get("market", "us"),
        }

    def broker_status(self) -> dict:
        creds = self.credential_status()
        mode = self.cfg.get("trading_mode", "simulation")
        ok, errors = validate_trading_mode(self.cfg, mode, self.cfg.get("default_asset_class", "stocks"))
        return {
            "broker": "alpaca",
            "enabled": bool(self.cfg.get("alpaca", {}).get("enabled", True)),
            "trading_mode": mode,
            "paper": self._paper_mode(),
            "live_trading_enabled": bool(self.cfg.get("live_trading_enabled", False)),
            "credentials": creds,
            "ready": ok,
            "errors": errors,
            "native_lumibot": {
                "broker": "lumibot.brokers.Alpaca",
                "data": "lumibot.data_sources.alpaca_data.AlpacaData",
                "backtesting": "lumibot.backtesting.alpaca_backtesting.AlpacaBacktesting",
            },
        }

    def data_status(self) -> dict:
        creds = self.credential_status()
        return {
            "provider": "alpaca",
            "enabled": bool(self.cfg.get("alpaca", {}).get("data_enabled", True)),
            "configured": creds["configured"],
            "data_feed": self.cfg.get("alpaca", {}).get("data_feed", "iex"),
            "capabilities": {
                "stocks": {
                    "historical_bars": True,
                    "live_bars": True,
                    "quotes": True,
                    "trades": True,
                    "minute": True,
                    "daily": True,
                    "orb_compatible": True,
                },
                "options": {"historical_bars": True, "quotes": True, "contracts": True,
                            "orders": True, "multileg": True, "managed_tp_sl": True, "readiness": "tradable"},
                "crypto": {"historical_bars": True, "live_bars": True, "quotes": True,
                           "orders": True, "managed_tp_sl": True, "readiness": "tradable"},
            },
        }

    def asset_classes(self) -> list[dict]:
        mode = self.cfg.get("trading_mode", "simulation")
        result = []
        for asset_class in ("stocks", "options", "crypto"):
            block = self.cfg.get(asset_class, {})
            ok, errors = validate_trading_mode(self.cfg, mode, asset_class)
            result.append({
                "asset_class": asset_class,
                "enabled": bool(block.get("enabled", False)),
                "paper_enabled": bool(block.get("paper_enabled", False)),
                "live_enabled": bool(block.get("live_enabled", False)),
                "explicit_enablement": bool(block.get("explicit_enablement", asset_class == "stocks")),
                "approval_status": block.get("approval_status"),
                "account_approved": bool(block.get("account_approved", asset_class != "options")),
                "ready": ok,
                "errors": errors,
            })
        return result

    def account(self) -> dict:
        if not self.credential_status()["configured"]:
            return {"configured": False, "status": "not_configured", "account": None}
        try:
            broker = self._build_broker()
            account = broker.api.get_account()
            return {"configured": True, "status": "ok", "account": self._obj_to_dict(account)}
        except Exception as exc:
            return {"configured": True, "status": "error", "error": str(exc)}

    def positions(self) -> dict:
        if not self.credential_status()["configured"]:
            return {"configured": False, "status": "not_configured", "positions": []}
        try:
            broker = self._build_broker()
            positions = broker.api.get_all_positions()
            return {"configured": True, "status": "ok", "positions": [self._obj_to_dict(p) for p in positions]}
        except Exception as exc:
            return {"configured": True, "status": "error", "positions": [], "error": str(exc)}

    def orders(self) -> dict:
        if not self.credential_status()["configured"]:
            return {"configured": False, "status": "not_configured", "orders": []}
        try:
            broker = self._build_broker()
            orders = broker.api.get_orders()
            return {"configured": True, "status": "ok", "orders": [self._obj_to_dict(o) for o in orders]}
        except Exception as exc:
            return {"configured": True, "status": "error", "orders": [], "error": str(exc)}

    def asset_metadata(self, symbol: str) -> dict:
        normalized = symbol.upper()
        creds = self.credential_status()
        mock_enabled = bool(self.cfg.get("alpaca", {}).get("mock_paper_submission", False))
        mode = self.cfg.get("trading_mode", "simulation")
        if mode == "simulation" or (not creds["configured"] and mock_enabled):
            return {**MOCK_ASSETS.get(normalized, {
                "symbol": normalized,
                "asset_class": "us_equity",
                "tradable": True,
                "status": "active",
                "fractionable": True,
            }), "source": "mock"}
        if not creds["configured"]:
            return {
                "symbol": normalized,
                "asset_class": None,
                "tradable": False,
                "status": "not_configured",
                "fractionable": False,
                "source": "none",
                "error": "Alpaca credentials are not configured.",
            }
        try:
            asset = self._build_broker().api.get_asset(normalized)
            data = self._obj_to_dict(asset)
            return {
                "symbol": str(data.get("symbol") or normalized).upper(),
                "asset_class": data.get("asset_class") or data.get("class") or data.get("asset_type"),
                "tradable": bool(data.get("tradable", False)),
                "status": data.get("status"),
                "fractionable": bool(data.get("fractionable", False)),
                "source": "alpaca",
            }
        except Exception as exc:
            return {
                "symbol": normalized,
                "asset_class": None,
                "tradable": False,
                "status": "error",
                "fractionable": False,
                "source": "alpaca",
                "error": str(exc),
            }

    def prepare_order_payload(self, order: dict) -> dict:
        """Build an Alpaca-valid order payload for the order's asset class.

        Dispatches to per-asset-class builders so each class only carries the fields
        Alpaca actually accepts (e.g. options use whole contracts + OCC symbols and never
        extended hours; crypto trades 24/7 with gtc and supports notional/fractional).
        """
        asset_class = order.get("asset_class", "stocks")
        if asset_class == "options":
            return self._prepare_options_payload(order)
        if asset_class == "crypto":
            return self._prepare_crypto_payload(order)
        return self._prepare_stock_payload(order)

    def _client_order_id(self, order: dict) -> str:
        return order.get("client_order_id") or f"tb2-{order.get('id', 'x')}-{uuid.uuid4().hex[:10]}"

    def _prepare_stock_payload(self, order: dict) -> dict:
        notional = order.get("notional")
        if order.get("sizing_mode") == "notional":
            notional = notional or order.get("dollar_amount")
        qty = order.get("quantity")
        extended_hours = bool(order.get("extended_hours", False))
        payload: dict[str, Any] = {
            "asset_class": "stocks",
            "symbol": order["symbol"],
            "side": order["side"],
            "type": order.get("order_type", "market"),
            "time_in_force": order.get("time_in_force") or "day",
            "extended_hours": extended_hours,
            "client_order_id": self._client_order_id(order),
        }
        if extended_hours:
            # Alpaca only accepts limit + day orders in pre/post-market.
            if str(payload["type"]).lower() != "limit":
                raise ValueError("Extended-hours orders must be limit orders.")
            if str(payload["time_in_force"]).lower() != "day":
                raise ValueError("Extended-hours orders must use time_in_force=day.")
            if order.get("limit_price") is None:
                raise ValueError("Extended-hours limit orders require a limit_price.")
        if order.get("sizing_mode") == "notional":
            if notional is None:
                raise ValueError("Stock notional order requires notional.")
            payload["notional"] = notional
            payload["time_in_force"] = "day"
        elif notional is not None and qty is not None:
            raise ValueError("Alpaca order payload cannot include both quantity and notional.")
        elif notional is not None:
            payload["notional"] = notional
        elif qty is not None:
            payload["qty"] = qty
        else:
            raise ValueError("Order requires quantity or notional.")
        for key in ("limit_price", "stop_price"):
            if order.get(key) is not None:
                payload[key] = order[key]
        return payload

    def _prepare_options_payload(self, order: dict) -> dict:
        """Options: whole contracts, OCC contract symbol(s), no extended hours, tif=day.

        Single-leg uses the OCC contract symbol as ``symbol``. Multi-leg uses
        ``order_class=mleg`` with a ``legs`` list (each an OCC symbol + side + ratio).
        """
        order_type = str(order.get("order_type", "market")).lower()
        # Options do not reliably support plain stop/market-stop; stop intents become limit.
        if order_type not in {"market", "limit"}:
            order_type = "limit"
        coid = self._client_order_id(order)

        legs = order.get("legs")
        if legs:
            payload: dict[str, Any] = {
                "asset_class": "options",
                "order_class": "mleg",
                "type": order_type,
                "time_in_force": "day",
                "client_order_id": coid,
                "qty": order.get("quantity"),
                "legs": [self._normalize_option_leg(leg) for leg in legs],
            }
            if payload["qty"] is None:
                raise ValueError("Multi-leg options order requires a contract quantity.")
            if order_type == "limit":
                if order.get("limit_price") is None:
                    raise ValueError("Options limit order requires limit_price (net debit/credit).")
                payload["limit_price"] = order["limit_price"]
            return payload

        contract = order.get("option_symbol") or order.get("symbol")
        if not contract:
            raise ValueError("Options order requires an OCC contract symbol (option_symbol).")
        qty = order.get("quantity")
        if qty is None:
            raise ValueError("Options order requires a whole-contract quantity.")
        if order.get("notional") is not None:
            raise ValueError("Options orders cannot use notional sizing.")
        payload = {
            "asset_class": "options",
            "symbol": str(contract).upper(),
            "side": order["side"],
            "type": order_type,
            "time_in_force": "day",
            "qty": qty,
            "client_order_id": coid,
            "underlying_symbol": order.get("underlying_symbol"),
            "option_type": order.get("option_type"),
            "strike": order.get("strike"),
            "expiration": order.get("expiration"),
        }
        if order_type == "limit":
            if order.get("limit_price") is None:
                raise ValueError("Options limit order requires limit_price.")
            payload["limit_price"] = order["limit_price"]
        return payload

    @staticmethod
    def _normalize_option_leg(leg: dict) -> dict:
        symbol = leg.get("symbol") or leg.get("option_symbol")
        side = leg.get("side")
        if not symbol or not side:
            raise ValueError("Each option leg requires symbol and side.")
        out = {"symbol": str(symbol).upper(), "side": str(side).lower(),
               "ratio_qty": int(leg.get("ratio_qty", 1))}
        if leg.get("position_intent"):
            out["position_intent"] = str(leg["position_intent"]).lower()
        return out

    def _prepare_crypto_payload(self, order: dict) -> dict:
        """Crypto: pair symbol (BTC/USD), 24/7, tif=gtc, no extended hours, notional/fractional ok."""
        order_type = str(order.get("order_type", "market")).lower()
        if order_type not in {"market", "limit", "stop_limit"}:
            # Crypto does not support plain stop / market-stop; fall back to limit.
            order_type = "limit"
        tif = str(order.get("time_in_force") or "gtc").lower()
        if tif == "day":
            tif = "gtc"
        payload: dict[str, Any] = {
            "asset_class": "crypto",
            "symbol": str(order["symbol"]).upper(),
            "side": order["side"],
            "type": order_type,
            "time_in_force": tif,
            "client_order_id": self._client_order_id(order),
        }
        notional = order.get("notional")
        if order.get("sizing_mode") == "notional" and notional is None:
            notional = order.get("dollar_amount")
        qty = order.get("quantity")
        if notional is not None and qty is not None:
            raise ValueError("Crypto order cannot include both quantity and notional.")
        if notional is not None:
            if order_type != "market":
                raise ValueError("Crypto notional orders must be market orders.")
            payload["notional"] = notional
        elif qty is not None:
            payload["qty"] = qty
        else:
            raise ValueError("Crypto order requires quantity or notional.")
        if order_type in {"limit", "stop_limit"}:
            if order.get("limit_price") is None:
                raise ValueError("Crypto limit/stop-limit order requires limit_price.")
            payload["limit_price"] = order["limit_price"]
        if order_type == "stop_limit":
            if order.get("stop_price") is None:
                raise ValueError("Crypto stop-limit order requires stop_price.")
            payload["stop_price"] = order["stop_price"]
        return payload

    def submit_order(self, order: dict) -> dict:
        mode = self.cfg.get("trading_mode", "simulation")
        ok, errors = validate_trading_mode(self.cfg, mode, order.get("asset_class", "stocks"))
        if mode == "simulation":
            return {
                "status": "accepted",
                "execution_status": "accepted",
                "broker_order_id": None,
                "paper": True,
                "details": {"mode": "simulation", "local_only": True},
            }
        if not ok:
            return {"status": "failed", "execution_status": "failed", "errors": errors}

        payload = self.prepare_order_payload(order)
        if mode == "paper" and self.cfg.get("alpaca", {}).get("mock_paper_submission", False):
            return {
                "status": "paper_submitted",
                "execution_status": "paper_submitted",
                "broker_order_id": f"paper-mock-{uuid.uuid4().hex[:12]}",
                "client_order_id": payload["client_order_id"],
                "paper": True,
                "details": {"mode": "paper", "mocked": True, "payload": payload},
            }
        if mode == "live" and not self.cfg.get("live_trading_enabled", False):
            return {"status": "failed", "execution_status": "failed", "errors": ["Live trading is disabled."]}
        # Real submission path (paper with mocking off, or live with the gate open).
        # Require credentials so we never silently no-op or leak a misconfiguration.
        if not self.credential_status()["configured"]:
            return {
                "status": "failed",
                "execution_status": "failed",
                "errors": ["Alpaca credentials are not configured; cannot submit a real order."],
                "details": {"mode": mode, "mocked": False, "payload": payload},
            }
        try:
            response = self._submit_to_alpaca_api(payload)
            raw_status = self._read_response_value(response, "status")
            broker_order_id = self._read_response_value(response, "id")
            client_order_id = self._read_response_value(response, "client_order_id") or payload["client_order_id"]
            paper = mode == "paper"
            mapped_status = self.map_order_status(str(raw_status or ""), paper=paper)
            if mapped_status in {"accepted", "failed"} and str(raw_status or "").lower() not in {"rejected", "suspended"}:
                mapped_status = "paper_submitted" if paper else "live_submitted"
            return {
                "status": mapped_status,
                "execution_status": mapped_status,
                "broker_order_id": broker_order_id,
                "client_order_id": client_order_id,
                "paper": paper,
                "details": {
                    "mode": mode,
                    "mocked": False,
                    "alpaca_status": str(raw_status) if raw_status is not None else None,
                    "payload": payload,
                },
            }
        except Exception as exc:
            return {
                "status": "failed",
                "execution_status": "failed",
                "errors": [str(exc)],
                "details": {"mode": mode, "mocked": False, "payload": payload},
            }

    def effective_data_feed(self, *, extended_hours: bool = False) -> str:
        """Data feed to use for the current session.

        Outside RTH (when extended hours is active and allowed) we use the configured
        ``extended_hours_data_feed`` (``sip`` by default) because ``iex`` is sparse.
        """
        alpaca = self.cfg.get("alpaca", {})
        if extended_hours and alpaca.get("allow_extended_hours", False):
            return str(alpaca.get("extended_hours_data_feed", "sip")).lower()
        return str(alpaca.get("data_feed", "iex")).lower()

    def map_order_status(self, status: str, *, paper: bool = True) -> str:
        normalized = (status or "").lower()
        mapping = {
            "new": "accepted",
            "accepted": "accepted",
            "pending_new": "accepted",
            "partially_filled": "partially_filled",
            "filled": "paper_filled" if paper else "live_filled",
            "done_for_day": "accepted",
            "canceled": "canceled",
            "expired": "canceled",
            "rejected": "rejected",
            "suspended": "failed",
            "calculated": "accepted",
        }
        return mapping.get(normalized, "failed")

    def test_connection(self) -> dict:
        if not self.credential_status()["configured"]:
            return {"status": "not_configured", "ok": False}
        account = self.account()
        return {"status": account.get("status"), "ok": account.get("status") == "ok", "account": account.get("account")}

    def _submit_to_alpaca_api(self, payload: dict):
        from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, StopLimitOrderRequest, StopOrderRequest

        order_type = str(payload.get("type") or "market").lower()
        if str(payload.get("order_class") or "").lower() == "mleg":
            return self._submit_mleg_to_alpaca_api(payload)
        side = OrderSide(str(payload.get("side") or "").lower())
        tif = TimeInForce(str(payload.get("time_in_force") or "day").lower())
        base_kwargs = {
            "symbol": payload["symbol"],
            "side": side,
            "time_in_force": tif,
            "client_order_id": payload["client_order_id"],
        }
        if payload.get("extended_hours"):
            base_kwargs["extended_hours"] = True
        if payload.get("qty") is not None and payload.get("notional") is not None:
            raise ValueError("Alpaca order cannot include both qty and notional.")
        if payload.get("qty") is not None:
            base_kwargs["qty"] = float(payload["qty"])
        elif payload.get("notional") is not None:
            base_kwargs["notional"] = float(payload["notional"])
        else:
            raise ValueError("Order requires quantity or notional.")

        if order_type == "market":
            request = MarketOrderRequest(type=OrderType.MARKET, **base_kwargs)
        elif order_type == "limit":
            if payload.get("limit_price") is None:
                raise ValueError("Limit order requires limit_price.")
            request = LimitOrderRequest(type=OrderType.LIMIT, limit_price=float(payload["limit_price"]), **base_kwargs)
        elif order_type == "stop":
            if payload.get("stop_price") is None:
                raise ValueError("Stop order requires stop_price.")
            request = StopOrderRequest(type=OrderType.STOP, stop_price=float(payload["stop_price"]), **base_kwargs)
        elif order_type == "stop_limit":
            if payload.get("stop_price") is None or payload.get("limit_price") is None:
                raise ValueError("Stop-limit order requires stop_price and limit_price.")
            request = StopLimitOrderRequest(
                type=OrderType.STOP_LIMIT,
                stop_price=float(payload["stop_price"]),
                limit_price=float(payload["limit_price"]),
                **base_kwargs,
            )
        else:
            raise ValueError(f"Unsupported Alpaca order type: {order_type}.")

        return self._build_broker().api.submit_order(order_data=request)

    def _submit_mleg_to_alpaca_api(self, payload: dict):
        """Submit a multi-leg options order (OrderClass.MLEG + per-leg OptionLegRequest)."""
        from alpaca.trading.enums import OrderClass, OrderSide, PositionIntent, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest, OptionLegRequest

        tif = TimeInForce(str(payload.get("time_in_force") or "day").lower())
        legs = []
        for leg in payload.get("legs", []):
            leg_kwargs = {
                "symbol": leg["symbol"],
                "side": OrderSide(str(leg["side"]).lower()),
                "ratio_qty": int(leg.get("ratio_qty", 1)),
            }
            if leg.get("position_intent"):
                leg_kwargs["position_intent"] = PositionIntent(str(leg["position_intent"]).lower())
            legs.append(OptionLegRequest(**leg_kwargs))
        common = {
            "qty": float(payload["qty"]),
            "time_in_force": tif,
            "client_order_id": payload["client_order_id"],
            "order_class": OrderClass.MLEG,
            "legs": legs,
        }
        order_type = str(payload.get("type") or "market").lower()
        if order_type == "limit":
            if payload.get("limit_price") is None:
                raise ValueError("Multi-leg limit order requires limit_price.")
            request = LimitOrderRequest(limit_price=float(payload["limit_price"]), **common)
        else:
            request = MarketOrderRequest(**common)
        return self._build_broker().api.submit_order(order_data=request)

    def _paper_mode(self) -> bool:
        env_var = self.cfg.get("alpaca", {}).get("is_paper_env_var", "ALPACA_IS_PAPER")
        raw = os.environ.get(env_var)
        if raw is not None:
            return raw.lower() in {"1", "true", "yes"}
        return self.cfg.get("trading_mode") != "live" or bool(self.cfg.get("alpaca", {}).get("paper", True))

    def _selected_credentials(self) -> dict:
        alpaca = self.cfg.get("alpaca", {})
        mode = self.cfg.get("trading_mode", "simulation")
        api_key_var = alpaca.get("api_key_env_var", "ALPACA_API_KEY")
        api_secret_var = alpaca.get("api_secret_env_var", "ALPACA_API_SECRET")
        oauth_var = alpaca.get("oauth_token_env_var", "ALPACA_OAUTH_TOKEN")

        if mode == "live":
            api_key = os.environ.get("ALPACA_LIVE_API_KEY") or os.environ.get(api_key_var)
            api_secret = os.environ.get("ALPACA_LIVE_API_SECRET") or os.environ.get(api_secret_var)
        else:
            api_key = os.environ.get("ALPACA_PAPER_API_KEY") or os.environ.get(api_key_var)
            api_secret = os.environ.get("ALPACA_PAPER_API_SECRET") or os.environ.get(api_secret_var)

        return {
            "api_key": api_key,
            "api_secret": api_secret,
            "oauth_token": os.environ.get(oauth_var),
        }

    def _build_broker(self):
        from lumibot.brokers import Alpaca

        return Alpaca(self.lumibot_config(), connect_stream=False)

    @staticmethod
    def _read_response_value(response: object, key: str):
        if response is None:
            return None
        if isinstance(response, dict):
            return response.get(key)
        return getattr(response, key, None)

    @staticmethod
    def _obj_to_dict(obj: object) -> dict:
        if obj is None:
            return {}
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return {"value": str(obj)}
