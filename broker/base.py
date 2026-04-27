#!/usr/bin/env python3
"""Broker base class and data models"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import json
import os
from pathlib import Path


@dataclass
class BrokerStatus:
    connected: bool = False
    user_name: Optional[str] = None
    user_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Position:
    exchange: str
    symbol: str
    product: str
    quantity: int
    average_price: float
    current_price: float
    unrealised_pnl: float
    realised_pnl: float
    instrument_token: int

    @property
    def net_value(self) -> float:
        return self.unrealised_pnl + self.realised_pnl

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


@dataclass
class Order:
    order_id: str
    exchange: str
    symbol: str
    product: str
    quantity: int
    price: float
    trigger_price: float
    status: str
    order_type: str
    side: str
    created_at: str
    updated_at: str
    filled_qty: int
    average_price: float

    @property
    def is_open(self) -> bool:
        return self.status.upper() in ("OPEN", "TRIGGER PENDING", "AMO")

    @property
    def is_complete(self) -> bool:
        return self.status.upper() in ("COMPLETE", "FILLED")

    @property
    def is_rejected(self) -> bool:
        return self.status.upper() in ("REJECTED", "CANCELLED")


class BaseBroker(ABC):
    """Abstract base class for broker integrations"""

    slug: str = "unknown"
    display_name: str = "Unknown Broker"
    logo: str = ""

    def __init__(self, token_store_path: str = None):
        if token_store_path is None:
            token_store_path = str(Path(__file__).parent / f"{self.slug}_tokens.json")
        self.token_store = Path(token_store_path)
        self._tokens: dict = self._load_tokens()

    def _load_tokens(self) -> dict:
        if self.token_store.exists():
            try:
                return json.loads(self.token_store.read_text())
            except Exception:
                pass
        return {}

    def _save_tokens(self):
        try:
            self.token_store.write_text(json.dumps(self._tokens, indent=2))
        except Exception as e:
            print(f"⚠️  Failed to save tokens for {self.slug}: {e}")

    def _get_env(self, key: str, default: str = "") -> str:
        return os.environ.get(f"{self.slug.upper()}_{key}", default)

    @abstractmethod
    def status(self) -> BrokerStatus:
        """Check connection status"""
        pass

    @abstractmethod
    def get_auth_url(self) -> str:
        """Return OAuth login URL"""
        pass

    @abstractmethod
    def handle_callback(self, params: dict) -> BrokerStatus:
        """Handle OAuth callback"""
        pass

    def authenticate(self) -> BrokerStatus:
        """Direct auth for non-OAuth brokers"""
        return self.status()

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Fetch open positions"""
        pass

    @abstractmethod
    def get_orders(self) -> list[Order]:
        """Fetch today's orders"""
        pass

    @abstractmethod
    def get_available_margin(self) -> float:
        """Available margin/buying power"""
        pass

    @abstractmethod
    def place_order(self, symbol: str, exchange: str, side: str, quantity: int,
                    product: str, order_type: str, price: float = 0,
                    trigger_price: float = 0) -> dict:
        """Place an order"""
        pass

    def disconnect(self) -> bool:
        """Clear stored tokens"""
        self._tokens = {}
        if self.token_store.exists():
            self.token_store.unlink()
        return True

    def is_connected(self) -> bool:
        return self.status().connected