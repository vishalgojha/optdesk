#!/usr/bin/env python3
"""Trade Executor — converts signal engine output into broker orders"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB = Path(__file__).parent / "optionchain.db"


def build_order_params(signal: dict, symbol: str = "NIFTY") -> Optional[dict]:
    """
    Convert signal engine output into broker order parameters.

    For NSE options:
    - Exchange: NFO (NSE Futures & Options)
    - Symbol format: NIFTY26MAY24000CE (example)

    Returns dict with order params or None if no valid trade.
    """
    trade_plan = signal.get("trade_plan", {})
    direction = trade_plan.get("direction")
    entry = trade_plan.get("entry")
    sl = trade_plan.get("stop_loss")
    target = trade_plan.get("target")
    strategy = trade_plan.get("strategy", "")
    atm = signal.get("atm", 0)
    spot = signal.get("current_price", 0)

    if not direction or not entry:
        return None

    # Determine expiry from data
    expiry = _get_nearest_expiry(symbol)
    if not expiry:
        return None

    # Determine strike
    if direction == "LONG":
        strike = signal.get("resistance", atm)
        opt_type = "CE"
    else:
        strike = signal.get("support", atm)
        opt_type = "PE"

    # Round to nearest 100 for NIFTY
    strike = round(strike / 100) * 100

    # Map strategy to product type
    product_map = {
        "Bull Call Spread": "BOTH",
        "Bear Put Spread": "BOTH",
        "Buy ATM Call": "BULL",
        "Buy ATM Put": "BEAR",
        "Sell ATM Call": "SHORT",
        "Sell ATM Put": "SHORT",
    }
    product = product_map.get(strategy, "BOTH")

    # Quantity: 1 lot
    lot_size = _get_lot_size(symbol)
    quantity = lot_size

    # Build trading symbol
    expiry_str = _format_expiry(expiry)
    symbol_broker = f"{symbol.upper()}{expiry_str}{strike}{opt_type}"
    exchange = "NFO"

    # Stop loss buffer for options (SL hit probability is lower)
    sl_price = sl
    if not sl_price:
        sl_price = entry * (0.85 if direction == "LONG" else 1.15)

    return {
        "symbol": symbol_broker,
        "exchange": exchange,
        "side": "BUY" if direction == "LONG" else "SELL",
        "quantity": quantity,
        "product": product,
        "order_type": "MARKET",
        "entry_price": entry,
        "stop_loss": sl_price,
        "target": target,
        "strategy": strategy,
        "signal": signal.get("signal"),
        "confidence": signal.get("confidence"),
        "bias": signal.get("bias"),
        "timestamp": datetime.now().isoformat(),
    }


def place_order_from_signal(signal: dict, broker_slug: str = "zerodha") -> dict:
    """Fetch order params and place order via broker"""
    params = build_order_params(signal)
    if not params:
        return {"success": False, "error": "No valid trade from signal"}

    try:
        sys_path = str(Path(__file__).parent)
        import sys
        sys.path.insert(0, sys_path)
        from broker.registry import get_broker

        broker = get_broker(broker_slug)
        if not broker.is_connected():
            return {"success": False, "error": f"{broker_slug} not connected"}

        result = broker.place_order(
            symbol=params["symbol"],
            exchange=params["exchange"],
            side=params["side"],
            quantity=params["quantity"],
            product=params["product"],
            order_type=params["order_type"],
        )

        if result.get("success"):
            _log_trade(params, result)
            return {**result, "order_params": params}

        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_nearest_expiry(symbol: str) -> Optional[str]:
    """Get nearest weekly expiry"""
    conn = sqlite3.connect(str(DB))
    row = conn.execute(
        "SELECT DISTINCT expiry FROM snapshots WHERE symbol = ? ORDER BY expiry ASC",
        (symbol,)
    ).fetchone()
    conn.close()
    if row:
        return row[0]
    return _guess_expiry()


def _guess_expiry() -> str:
    """Fallback: guess nearest Thursday expiry"""
    from datetime import datetime, timedelta
    today = datetime.now()
    days_ahead = (3 - today.weekday() + 7) % 7 or 7
    if today.weekday() == 3:
        days_ahead = 7
    expiry = today + timedelta(days=days_ahead)
    return expiry.strftime("%d%b%Y").upper()


def _format_expiry(expiry: str) -> str:
    """Convert '2025-05-29' → '29MAY25'"""
    try:
        if "-" in expiry:
            dt = datetime.strptime(expiry[:10], "%Y-%m-%d")
        else:
            dt = datetime.strptime(expiry, "%Y-%m-%d")
        return dt.strftime("%d%b%y").upper()
    except Exception:
        return _guess_expiry()


def _get_lot_size(symbol: str = "NIFTY") -> int:
    """NIFTY lot sizes"""
    return {"NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 40}.get(symbol, 25)


def _log_trade(params: dict, result: dict):
    """Log executed trade to DB"""
    conn = sqlite3.connect(str(DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, exchange TEXT, side TEXT,
            quantity INTEGER, product TEXT, order_type TEXT,
            entry_price REAL, stop_loss REAL, target REAL,
            strategy TEXT, order_id TEXT, signal TEXT,
            confidence REAL, bias TEXT,
            UNIQUE(timestamp, symbol, side, quantity)
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO trades
        (timestamp, symbol, exchange, side, quantity, product, order_type,
         entry_price, stop_loss, target, strategy, order_id, signal, confidence, bias)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        params["timestamp"], params["symbol"], params["exchange"], params["side"],
        params["quantity"], params["product"], params["order_type"],
        params["entry_price"], params["stop_loss"], params["target"],
        params["strategy"], result.get("order_id", ""), params["signal"],
        params["confidence"], params["bias"],
    ))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from engine.signal_engine import get_signal

    sig = get_signal("NIFTY")
    params = build_order_params(sig)
    if params:
        print(json.dumps(params, indent=2, default=str))
    else:
        print("No trade from current signal")