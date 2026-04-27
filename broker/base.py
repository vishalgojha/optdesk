#!/usr/bin/env python3
"""Broker base class and data models for optdesk"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json
import os
from pathlib import Path


@dataclass
class AuthStatus:
    connected: bool
    broker: str
    user_name: str = ""
    user_id: str = ""
    error: str = ""
    token_expires: Optional[datetime] = None


@dataclass
class OptionSymbol:
    raw: str
    broker_symbol: str
    index: str
    strike: int
    option_type: str
    expiry: str
    lot_size: int = 50


@dataclass
class OrderResult:
    success: bool
    order_id: str = ""
    broker: str = ""
    symbol: str = ""
    quantity: int = 0
    side: str = ""
    order_type: str = ""
    price: float = 0.0
    status: str = ""
    message: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class Position:
    symbol: str
    broker_symbol: str
    quantity: int
    average_price: float
    ltp: float
    pnl: float
    product: str
    broker: str


@dataclass
class OrderBook:
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    status: str
    order_type: str
    placed_at: Optional[datetime]
    broker: str


class BrokerBase(ABC):
    NAME: str = "unknown"
    PACKAGE: str = ""
    ENV_PREFIX: str = ""

    def __init__(self, token_store_path: str = None):
        if token_store_path is None:
            token_store_path = str(Path(__file__).parent / f"{self.__class__.__name__.lower().replace('broker', '')}_tokens.json")
        self.token_store = Path(token_store_path)
        self._tokens: dict = self._load_tokens()
        self._last_error: str = ""
        self._last_check: Optional[datetime] = None

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
            print(f"⚠️  Failed to save tokens: {e}")

    def _get_env(self, key: str, default: str = "") -> str:
        return os.environ.get(f"{self.ENV_PREFIX}_{key}", default)

    @abstractmethod
    def get_auth_url(self) -> str:
        pass

    @abstractmethod
    def handle_callback(self, params: dict) -> AuthStatus:
        pass

    @abstractmethod
    def status(self) -> AuthStatus:
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        pass

    @abstractmethod
    def resolve_option_symbol(self, index: str, strike: int, option_type: str, expiry: str) -> OptionSymbol:
        pass

    @abstractmethod
    def place_order(self, symbol: OptionSymbol, side: str, quantity: int,
                    order_type: str = "MARKET", price: float = 0.0, product: str = "INTRADAY") -> OrderResult:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult:
        pass

    @abstractmethod
    def get_positions(self) -> list[Position]:
        pass

    @abstractmethod
    def get_orders(self) -> list[OrderBook]:
        pass

    @abstractmethod
    def get_available_margin(self) -> float:
        pass

    def is_connected(self) -> bool:
        return self.status().connected

    def health_check(self) -> dict:
        now = datetime.now()
        self._last_check = now
        try:
            status = self.status()
            self._last_error = status.error if status.error else ""
            connected = status.connected
            margin = self.get_available_margin() if connected else 0
            return {
                "broker": self.NAME,
                "healthy": connected,
                "connected": connected,
                "margin": margin,
                "last_check": now.isoformat(),
                "error": self._last_error,
            }
        except Exception as e:
            self._last_error = str(e)
            return {
                "broker": self.NAME,
                "healthy": False,
                "connected": False,
                "margin": 0,
                "last_check": now.isoformat(),
                "error": str(e),
            }

    def ping(self) -> bool:
        try:
            return self.status().connected
        except Exception:
            return False

    def validate_env(self, required_vars: list[str]) -> tuple[bool, list[str]]:
        missing = [v for v in required_vars if not self._get_env(v)]
        return len(missing) == 0, missing