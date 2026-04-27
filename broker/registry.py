#!/usr/bin/env python3
"""Broker registry — manages all broker connector instances"""

import os
from typing import Optional
from .base import BrokerBase


def _load_zerodha():
    from .zerodha import ZerodhaConnector
    return ZerodhaConnector()


def _load_upstox():
    from .upstox import UpstoxConnector
    return UpstoxConnector()


def _load_angel():
    from .angel import AngelConnector
    return AngelConnector()


def _load_fyers():
    from .fyers_connector import FyersConnector
    return FyersConnector()


BROKERS: dict[str, tuple[str, callable, list[str]]] = {
    "zerodha": (
        "Zerodha (Kite Connect)",
        _load_zerodha,
        ["ZERODHA_API_KEY", "ZERODHA_API_SECRET"],
    ),
    "upstox": (
        "Upstox",
        _load_upstox,
        ["UPSTOX_API_KEY", "UPSTOX_API_SECRET"],
    ),
    "angel": (
        "Angel One (SmartAPI)",
        _load_angel,
        ["ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_MPIN", "ANGEL_TOTP_SECRET"],
    ),
    "fyers": (
        "Fyers",
        _load_fyers,
        ["FYERS_CLIENT_ID", "FYERS_SECRET_KEY"],
    ),
}

_instances: dict[str, BrokerBase] = {}


def get_broker(slug: str) -> BrokerBase:
    slug = slug.lower()
    if slug not in BROKERS:
        raise KeyError(f"Unknown broker '{slug}'. Available: {list(BROKERS)}")
    if slug not in _instances:
        _, loader, _ = BROKERS[slug]
        _instances[slug] = loader()
    return _instances[slug]


def list_brokers() -> list[dict]:
    result = []
    for slug, (display_name, _, required_env) in BROKERS.items():
        configured = all(os.getenv(var) for var in required_env)
        try:
            broker = get_broker(slug)
            status = broker.status()
            connected = status.connected
            user = status.user_name
        except Exception:
            connected = False
            user = ""
        result.append({
            "slug": slug,
            "name": display_name,
            "configured": configured,
            "connected": connected,
            "user": user,
            "required_env": required_env,
        })
    return result


def close_all():
    for broker in _instances.values():
        try:
            if hasattr(broker, "close"):
                broker.close()
        except Exception:
            pass
    _instances.clear()