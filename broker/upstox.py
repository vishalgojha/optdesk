#!/usr/bin/env python3
"""Upstox broker integration"""

import os
from .base import BrokerBase, AuthStatus, Position, OrderBook


class UpstoxConnector(BrokerBase):
    NAME = "upstox"
    ENV_PREFIX = "UPSTOX"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None

    def _init_client(self):
        if self.client is not None:
            return True
        try:
            from upstox import Upstox
            api_key = self._get_env("API_KEY")
            access_token = self._tokens.get("access_token")
            if not api_key or not access_token:
                return False
            self.client = Upstox(api_key=api_key, access_token=access_token)
            return True
        except ImportError:
            raise ImportError("Install upstox: pip install upstox")
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
                user_id=profile.get("user_id", ""),
            )
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def get_auth_url(self) -> str:
        from upstox import Upstox
        api_key = self._get_env("API_KEY")
        if not api_key:
            raise ValueError("UPSTOX_API_KEY not set")
        client = Upstox(api_key=api_key)
        return client.get_login_url()

    def handle_callback(self, params: dict) -> AuthStatus:
        request_token = params.get("request_token", "")
        if not request_token:
            return AuthStatus(connected=False, error="Missing request_token")

        try:
            from upstox import Upstox
            api_key = self._get_env("API_KEY")
            api_secret = self._get_env("API_SECRET")
            if not api_key or not api_secret:
                return AuthStatus(connected=False, error="API credentials not set")

            client = Upstox(api_key=api_key)
            data = client.generate_session(request_token, api_secret)
            self._tokens["access_token"] = data.get("access_token")
            self._save_tokens()
            self.client = client
            return AuthStatus(connected=True)
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
                    quantity=int(p.get("quantity", 0)),
                    average_price=float(p.get("avg_price", 0)),
                    ltp=float(p.get("ltp", 0)),
                    pnl=float(p.get("pnl", 0)),
                    product=p.get("product", ""),
                    broker="upstox",
                )
                for p in positions
            ]
        except Exception:
            return []

    def get_orders(self) -> list[OrderBook]:
        if not self._init_client():
            return []
        try:
            orders = self.client.get_orders()
            return [
                OrderBook(
                    order_id=str(o.get("order_id", "")),
                    symbol=o.get("symbol", ""),
                    side=o.get("side", ""),
                    quantity=int(o.get("quantity", 0)),
                    price=float(o.get("price", 0)),
                    status=o.get("status", ""),
                    order_type=o.get("order_type", ""),
                    placed_at=o.get("timestamp", None),
                    broker="upstox",
                )
                for o in orders
            ]
        except Exception:
            return []

    def get_available_margin(self) -> float:
        if not self._init_client():
            return 0.0
        try:
            margin = self.client.get_margin()
            return float(margin.get("available_margin", 0))
        except Exception:
            return 0.0

    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str = "MIS", order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Upstox")
        try:
            order_id = self.client.place_order(
                exchange=exchange,
                symbol=symbol,
                transaction_type=side.upper(),
                quantity=quantity,
                product=product,
                order_type=order_type.upper(),
                price=price,
                trigger_price=trigger_price,
            )
            return {"success": True, "order_id": order_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        if not self._init_client():
            raise ValueError("Not connected to Upstox")
        try:
            self.client.cancel_order(order_id)
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