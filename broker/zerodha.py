#!/usr/bin/env python3
"""Zerodha Kite Connect broker integration"""

import os
from datetime import datetime
from .base import BrokerBase, AuthStatus, Position, OrderBook


class ZerodhaConnector(BrokerBase):
    slug = "zerodha"
    display_name = "Zerodha"
    logo = "zerodha.svg"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kite = None

    def _init_kite(self):
        if self.kite is not None:
            return True
        try:
            from kiteconnect import KiteConnect
            api_key = self._get_env("API_KEY")
            access_token = self._tokens.get("access_token")
            if not api_key or not access_token:
                return False
            self.kite = KiteConnect(api_key=api_key)
            self.kite.set_access_token(access_token)
            return True
        except ImportError:
            raise ImportError("Install kiteconnect: pip install kiteconnect")
        except Exception:
            return False

    def status(self) -> AuthStatus:
        try:
            if not self._init_kite():
                return AuthStatus(connected=False, error="Not authenticated")
            profile = self.kite.profile()
            return AuthStatus(
                connected=True,
                user_name=profile.get("user_name"),
                user_id=profile.get("user_id"),
            )
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def get_auth_url(self) -> str:
        from kiteconnect import KiteConnect
        api_key = self._get_env("API_KEY")
        if not api_key:
            raise ValueError("ZERODHA_API_KEY not set")
        kite = KiteConnect(api_key=api_key)
        return kite.login_url()

    def handle_callback(self, params: dict) -> AuthStatus:
        request_token = params.get("request_token", "")
        if not request_token:
            return AuthStatus(connected=False, error="Missing request_token")

        try:
            from kiteconnect import KiteConnect
            api_key = self._get_env("API_KEY")
            api_secret = self._get_env("API_SECRET")
            if not api_key or not api_secret:
                return AuthStatus(connected=False, error="API credentials not set")

            kite = KiteConnect(api_key=api_key)
            data = kite.generate_session(request_token, api_secret)
            self._tokens["access_token"] = data["data"]["access_token"]
            self._tokens["user_id"] = data["data"]["user_id"]
            self._save_tokens()
            self.kite = kite
            self.kite.set_access_token(data["data"]["access_token"])
            return AuthStatus(connected=True, user_name=data["data"]["user_name"])
        except Exception as e:
            return AuthStatus(connected=False, error=str(e))

    def get_positions(self) -> list[Position]:
        if not self._init_kite():
            return []
        try:
            data = self.kite.positions()["net"]
            return [
                Position(
                    symbol=r.get("tradingsymbol", ""),
                    broker_symbol=r.get("tradingsymbol", ""),
                    quantity=int(r.get("quantity", 0)),
                    average_price=float(r.get("average_price", 0)),
                    ltp=float(r.get("last_price", 0)),
                    pnl=float(r.get("unrealised", 0)),
                    product=r.get("product", ""),
                    broker="zerodha",
                )
                for r in data
            ]
        except Exception:
            return []

    def get_orders(self) -> list[OrderBook]:
        if not self._init_kite():
            return []
        try:
            orders = self.kite.orders()
            return [
                OrderBook(
                    order_id=str(r.get("order_id", "")),
                    symbol=r.get("tradingsymbol", ""),
                    side="BUY" if r.get("transaction_type", "") == "BUY" else "SELL",
                    quantity=int(r.get("quantity", 0)),
                    price=float(r.get("price", 0)),
                    status=r.get("status", ""),
                    order_type=r.get("order_type", ""),
                    placed_at=r.get("order_timestamp", None),
                    broker="zerodha",
                )
                for r in orders
            ]
        except Exception:
            return []

    def get_available_margin(self) -> float:
        if not self._init_kite():
            return 0.0
        try:
            margin = self.kite.margins()
            return float(margin.get("equity", {}).get("available", {}).get("live_balance", 0))
        except Exception:
            return 0.0

    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str = "MIS", order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0) -> dict:
        if not self._init_kite():
            raise ValueError("Not connected to Zerodha")
        try:
            order_id = self.kite.place_order(
                variety="regular",
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=side.upper(),
                quantity=quantity,
                product=product,
                order_type=order_type.upper(),
                price=price if price else 0,
                trigger_price=trigger_price if trigger_price else 0,
            )
            return {"success": True, "order_id": order_id}
        except Exception as e:
            return {"success": False, "error": str(e)}