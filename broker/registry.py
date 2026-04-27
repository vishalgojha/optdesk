#!/usr/bin/env python3
"""Broker registry — manages all broker instances"""

import os
from typing import Optional

_brokers: dict = {}


def _lazy_import(name: str) -> type:
    """Lazy-load broker implementation to avoid hard dependencies"""
    if name == "zerodha":
        from .zerodha import ZerodhaBroker
        return ZerodhaBroker
    elif name == "angelone":
        from .angelone import AngelOneBroker
        return AngelOneBroker
    raise KeyError(f"Unknown broker: {name}")


def get_broker(slug: str, **kwargs) -> "BaseBroker":
    """Get or create broker instance by slug"""
    if slug not in _brokers:
        cls = _lazy_import(slug)
        _brokers[slug] = cls(**kwargs)
    return _brokers[slug]


def list_brokers() -> list[dict]:
    """List all supported brokers with connection status"""
    supported = ["zerodha", "angelone"]

    result = []
    for slug in supported:
        try:
            cls = _lazy_import(slug)
            broker = get_broker(slug)
            status = broker.status()
            result.append({
                "slug": slug,
                "display_name": cls.display_name,
                "logo": cls.logo,
                "connected": status.connected,
                "user_name": status.user_name,
                "auth_type": "oauth2" if slug == "zerodha" else "direct",
                "required_env": {
                    "zerodha": ["ZERODHA_API_KEY", "ZERODHA_API_SECRET"],
                    "angelone": ["ANGELONE_CLIENT_ID", "ANGELONE_PASSWORD", "ANGELONE_TOTP_SECRET"],
                }.get(slug, []),
            })
        except ImportError:
            result.append({
                "slug": slug,
                "display_name": slug.replace("_", " ").title(),
                "available": False,
                "error": "Package not installed",
            })
        except Exception as e:
            result.append({
                "slug": slug,
                "display_name": slug.replace("_", " ").title(),
                "available": True,
                "error": str(e),
            })
    return result


def close_all():
    """Close all broker connections"""
    for broker in _brokers.values():
        try:
            if hasattr(broker, "close"):
                broker.close()
        except Exception:
            pass
    _brokers.clear()