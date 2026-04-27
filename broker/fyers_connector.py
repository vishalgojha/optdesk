#!/usr/bin/env python3
"""Fyers broker integration"""

import os
from .base import BrokerBase, AuthStatus, Position, OrderBook


class FyersConnector(BrokerBase):
    NAME = "fyers"
    ENV_PREFIX = "FYERS"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None

    def _init_client(self):
        if self.client is not None:
            return True
        try:
            from fyers_api import fyersModel
            client_id = self._get_env("CLIENT_ID")
            access_token = self._tokens.get("access_token")
            if not client_id or not access_token:
                return False
            self.client = fyersModel.FyersModel(client_id=client_id, token=access_token)
            return True
        except ImportError:
            raise ImportError("Install fyers-api: pip install fyers-api")
        except Exception:
            return False

    def status(self) -> AuthStatus:
        try:
            if not self._init_client():
                return AuthStatus(connected=False, error="Not authenticated")
            profile = self.client.get_profile()
            return AuthStatus(
                connected=True,
                user_name=profile.get("name", ""),
                user_id=profile.get("fy_user_id", ""),
            )
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def get_auth_url(self) -> str:
        client_id = self._get_env("CLIENT_ID")
        if not client_id:
            raise ValueError("FYERS_CLIENT_ID not set")
        return f"https://api.fyers.in/api/v2/generate/auth?app_id={client_id}"

    def handle_callback(self, params: dict) -> AuthStatus:
        access_token = params.get("access_token", "")
        if not access_token:
            return AuthStatus(connected=False, error="Missing access_token")

        try:
            self._tokens["access_token"] = access_token
            self._save_tokens()
            return self.status()
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def disconnect(self) -> bool:
        self.client = None
        self._tokens.clear()
        self._save_tokens()
        return True

    def get_positions(self) -> list[Position]:
        if not self._init_client():
            return []
        try:
            positions = self.client.get_positions()
            return [
                Position(
                    symbol=p.get("symbol", ""),
                    broker_symbol=p.get("symbol", ""),
                    quantity=int(p.get("qty", 0)),
                    average_price=float(p.get("avg_price", 0)),
                    ltp=float(p.get("ltp", 0)),
                    pnl=float(p.get("pnl", 0)),
                    product=p.get("product", ""),
                    broker="fyers",
                )
                for p in positions
            ]
        except Exception:
            return []

    def get_orders(self) -> list[OrderBook]:
        if not self._init_client():
            return []
        try:
            orders = self.client.order_book()
            return [
                OrderBook(
                    order_id=str(o.get("id", "")),
                    symbol=o.get("symbol", ""),
                    side=o.get("side", ""),
                    quantity=int(o.get("qty", 0)),
                    price=float(o.get("price", 0)),
                    status=o.get("status", ""),
                    order_type=o.get("type", ""),
                    placed_at=o.get("date", None),
                    broker="fyers",
                )
                for o in orders
            ]
        except Exception:
            return []

    def get_available_margin(self) -> float:
        if not self._init_client():
            return 0.0
        try:
            margin = self.client.funds()
            return float(margin.get("fund_limit", [{}])[0].get("balance", 0))
        except Exception:
            return 0.0

    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str = "MIS", order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Fyers")
        try:
            order_id = self.client.place_order(
                type=order_type.upper(),
                side=side.upper(),
                symbol=symbol,
                qty=quantity,
                product=product,
                limit_price=int(price) if price else 0,
                stop_price=int(trigger_price) if trigger_price else 0,
            )
            return {"success": True, "order_id": order_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Fyers")
        try:
            self.client.cancel_order(id=order_id)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def resolve_option_symbol(self, index: str, strike: int, option_type: str, expiry: str):
        from .base import OptionSymbol
        symbol = f"{index}{strike}{option_type.upper()}"
        return OptionSymbol(
            raw=symbol,
            broker_symbol=symbol,
            index=index,
            strike=strike,
            option_type=option_type,
            expiry=expiry,
        )