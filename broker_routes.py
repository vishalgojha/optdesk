#!/usr/bin/env python3
"""Broker API routes for optdesk FastAPI"""

import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import JSONResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).parent))

try:
    from broker.registry import get_broker, list_brokers
    BROKER_AVAILABLE = True
except ImportError:
    BROKER_AVAILABLE = False

broker_router = APIRouter(tags=["broker"])


@broker_router.get("")
def get_all_brokers():
    if not BROKER_AVAILABLE:
        return []
    return list_brokers()


@broker_router.get("/{slug}/status")
def get_broker_status(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    status = broker.status()
    return {
        "broker": slug, "connected": status.connected,
        "user_name": status.user_name, "user_id": status.user_id, "error": status.error,
    }


@broker_router.get("/{slug}/auth-url")
def get_auth_url(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    url = broker.get_auth_url()
    return {"broker": slug, "url": url}


@broker_router.get("/callback")
def oauth_callback(request: Request):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    params = dict(request.query_params)
    slug = params.pop("broker", "")
    if not slug:
        return RedirectResponse("/?broker_error=missing_broker_param")
    try:
        broker = get_broker(slug)
    except KeyError:
        return RedirectResponse(f"/?broker_error=unknown_broker_{slug}")
    status = broker.handle_callback(params)
    if status.connected:
        return RedirectResponse(f"/?broker_connected={slug}&user={status.user_name}")
    return RedirectResponse(f"/?broker_error={slug}:{status.error}")


@broker_router.post("/{slug}/connect")
def direct_connect(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if hasattr(broker, "authenticate"):
        status = broker.authenticate()
    else:
        status = broker.status()
    return {"connected": status.connected, "user_name": status.user_name, "error": status.error}


@broker_router.post("/{slug}/disconnect")
def disconnect_broker(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ok = broker.disconnect()
    return {"broker": slug, "disconnected": ok}


@broker_router.get("/{slug}/positions")
def get_positions(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    positions = broker.get_positions()
    return [p.__dict__ for p in positions]


@broker_router.get("/{slug}/orders")
def get_orders(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    orders = broker.get_orders()
    return [o.__dict__ for o in orders]


@broker_router.get("/{slug}/margin")
def get_margin(slug: str):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    margin = broker.get_available_margin()
    return {"broker": slug, "available_margin": margin}


@broker_router.post("/{slug}/trade")
def execute_trade(slug: str, signal_json: str = Query(...)):
    if not BROKER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Broker module not available")
    try:
        broker = get_broker(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        signal = json.loads(signal_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signal JSON")

    try:
        from trade_executor import place_order_from_signal
        result = place_order_from_signal(signal, slug)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}