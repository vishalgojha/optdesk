#!/usr/bin/env python3
"""Angel One (SmartAPI) broker integration"""

import os
from .base import BrokerBase, AuthStatus, Position, OrderBook


class AngelConnector(BrokerBase):
    NAME = "angel"
    ENV_PREFIX = "ANGEL"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None

    def _init_client(self):
        if self.client is not None:
            return True
        try:
            from smartapi import SmartConnect
            api_key = self._get_env("API_KEY")
            access_token = self._tokens.get("access_token")
            if not api_key or not access_token:
                return False
            self.client = SmartConnect(api_key=api_key)
            self.client.setAccessToken(access_token)
            return True
        except ImportError:
            raise ImportError("Install smartapi: pip install smartapi")
        except Exception:
            return False

    def status(self) -> AuthStatus:
        try:
            if not self._init_client():
                return AuthStatus(connected=False, error="Not authenticated")
            profile = self.client.getProfile()
            return AuthStatus(
                connected=True,
                user_name=profile.get("name", ""),
                user_id=profile.get("clientcode", ""),
            )
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def get_auth_url(self) -> str:
        api_key = self._get_env("API_KEY")
        if not api_key:
            raise ValueError("ANGEL_API_KEY not set")
        return f"https://smartapi.angelone.in/smart-api/login?api_key={api_key}"

    def handle_callback(self, params: dict) -> AuthStatus:
        client_code = params.get("clientcode", "")
        password = params.get("password", "")
        totp = params.get("totp", "")

        if not client_code or not password or not totp:
            return AuthStatus(connected=False, error="Missing credentials")

        try:
            from smartapi import SmartConnect
            api_key = self._get_env("API_KEY")
            if not api_key:
                return AuthStatus(connected=False, error="API key not set")

            client = SmartConnect(api_key=api_key)
            data = client.generateSession(client_code, password, totp)
            self._tokens["access_token"] = data.get("data", {}).get("accessToken")
            self._tokens["user_id"] = client_code
            self._save_tokens()
            self.client = client
            return AuthStatus(connected=True, user_name=client_code)
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
            positions = self.client.position()
            return [
                Position(
                    symbol=p.get("symbol", ""),
                    broker_symbol=p.get("symbol", ""),
                    quantity=int(p.get("netqty", 0)),
                    average_price=float(p.get("avgncm", 0)),
                    ltp=float(p.get("ltp", 0)),
                    pnl=float(p.get("pnl", 0)),
                    product=p.get("producttype", ""),
                    broker="angel",
                )
                for p in positions
            ]
        except Exception:
            return []

    def get_orders(self) -> list[OrderBook]:
        if not self._init_client():
            return []
        try:
            orders = client.orderBook()
            return [
                OrderBook(
                    order_id=str(o.get("orderid", "")),
                    symbol=o.get("symbol", ""),
                    side=o.get("side", ""),
                    quantity=int(o.get("qty", 0)),
                    price=float(o.get("price", 0)),
                    status=o.get("status", ""),
                    order_type=o.get("type", ""),
                    placed_at=o.get("ordertime", None),
                    broker="angel",
                )
                for o in orders
            ]
        except Exception:
            return []

    def get_available_margin(self) -> float:
        if not self._init_client():
            return 0.0
        try:
            margin = self.client.rmsLimit()
            return float(margin.get("data", {}).get("availablecash", 0))
        except Exception:
            return 0.0

    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str = "MIS", order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Angel One")
        try:
            order_id = self.client.placeOrder(
                exchange=exchange,
                symbol=symbol,
                transactiontype=side.upper(),
                quantity=quantity,
                producttype=product,
                ordertype=order_type.upper(),
                price=int(price) if price else 0,
                triggerprice=int(trigger_price) if trigger_price else 0,
            )
            return {"success": True, "order_id": order_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Angel One")
        try:
            self.client.cancelOrder(order_id)
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