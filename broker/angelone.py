#!/usr/bin/env python3
"""Angel One Smart API broker integration"""

from datetime import datetime
from .base import BaseBroker, BrokerStatus, Position, Order


class AngelOneBroker(BaseBroker):
    slug = "angelone"
    display_name = "Angel One"
    logo = "angelone.svg"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = None

    def _init_client(self):
        if self.client is not None:
            return True
        try:
            from smartapi import SmartConnect

            client_id = self._get_env("CLIENT_ID")
            password = self._get_env("PASSWORD")
            totp_secret = self._get_env("TOTP_SECRET")

            if not all([client_id, password, totp_secret]):
                return False

            self.client = SmartConnect(api_key=self._get_env("API_KEY"))
            import pyotp
            totp = pyotp.TOTP(totp_secret)
            data = self.client.generateSession(client_id, password, totp.now())
            if data.get("status"):
                self._tokens["feed_token"] = self.client.getfeedToken()
                self._save_tokens()
                return True
            return False
        except ImportError:
            raise ImportError("Install smartapi: pip install smartapi")
        except Exception:
            return False

    def status(self) -> BrokerStatus:
        try:
            if not self._init_client():
                return BrokerStatus(connected=False, error="Not authenticated")
            profile = self.client.profile()
            if profile and profile.get("status"):
                return BrokerStatus(
                    connected=True,
                    user_name=profile.get("data", {}).get("name", ""),
                    user_id=profile.get("data", {}).get("clientId", ""),
                )
            return BrokerStatus(connected=False, error="Profile fetch failed")
        except Exception as e:
            return BrokerStatus(connected=False, error=str(e))

    def authenticate(self) -> BrokerStatus:
        """Authenticate using TOTP credentials from env vars"""
        self._init_client()
        return self.status()

    def get_auth_url(self) -> str:
        return ""  # Angel One uses direct auth, not OAuth

    def handle_callback(self, params: dict) -> BrokerStatus:
        return self.status()  # Not applicable for Angel One

    def get_positions(self) -> list[Position]:
        if not self.client:
            return []
        try:
            data = self.client.position()
            if not data or not data.get("data"):
                return []
            positions = []
            for r in data.get("data", []):
                if r.get("netQty", 0) != 0:
                    positions.append(Position(
                        exchange=r.get("exchange", ""),
                        symbol=r.get("symbol", ""),
                        product=r.get("productType", ""),
                        quantity=int(r.get("netQty", 0)),
                        average_price=float(r.get("avgPrice", 0)),
                        current_price=float(r.get("ltp", 0)),
                        unrealised_pnl=float(r.get("unrealised", 0)),
                        realised_pnl=float(r.get("realised", 0)),
                        instrument_token=0,
                    ))
            return positions
        except Exception:
            return []

    def get_orders(self) -> list[Order]:
        if not self.client:
            return []
        try:
            data = self.client.orderBook()
            if not data or not data.get("data"):
                return []
            return [
                Order(
                    order_id=str(r.get("orderid", "")),
                    exchange=r.get("exchange", ""),
                    symbol=r.get("symbol", ""),
                    product=r.get("producttype", ""),
                    quantity=int(r.get("quantity", 0)),
                    price=float(r.get("price", 0)),
                    trigger_price=float(r.get("triggerPrice", 0)),
                    status=r.get("status", ""),
                    order_type=r.get("orderType", ""),
                    side="BUY" if r.get("buyOrSell", "") == "BUY" else "SELL",
                    created_at=r.get("orderTime", ""),
                    updated_at=r.get("exchUpdateTime", ""),
                    filled_qty=int(r.get("filledQty", 0)),
                    average_price=float(r.get("averagePrice", 0)),
                )
                for r in data.get("data", [])
            ]
        except Exception:
            return []

    def get_available_margin(self) -> float:
        if not self.client:
            return 0.0
        try:
            data = self.client.rmsLimit()
            if data and data.get("data"):
                return float(data["data"].get("availablecash", 0))
        except Exception:
            pass
        return 0.0

    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str = "DELAM", order_type: str = "MARKET",
                    price: float = 0, trigger_price: float = 0) -> dict:
        if not self.client:
            raise ValueError("Not connected to Angel One")
        try:
            order_id = self.client.placeOrder(
                variety="NORMAL",
                exchange=exchange,
                symboltoken=symbol,
                buyOrSell=side.upper(),
                quantity=quantity,
                ordertype=order_type.upper(),
                producttype=product,
                price=str(price) if price else "0",
                triggerprice=str(trigger_price) if trigger_price else "0",
            )
            return {"success": True, "order_id": order_id.get("data", {}).get("orderid", "")}
        except Exception as e:
            return {"success": False, "error": str(e)}