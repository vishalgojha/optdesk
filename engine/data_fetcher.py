#!/usr/bin/env python3
"""Data Fetcher - Fetches live option chain data from NSE"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import nsepython
    HAS_NSE = True
except ImportError:
    HAS_NSE = False


DB = Path(__file__).parent.parent / "optionchain.db"
DEFAULT_SYMBOL = "NIFTY"


def fetch(symbol: str = DEFAULT_SYMBOL) -> Optional[dict]:
    if not HAS_NSE:
        return None

    for fn in [nsepython.option_chain, nsepython.nse_optionchain_scrapper, nsepython.oi_chain_builder]:
        try:
            data = fn(symbol)
            if data:
                if isinstance(data, list):
                    data = data[0]
                if "records" in data or "data" in data:
                    return data
        except Exception:
            pass
    return None


def persist(data: dict, symbol: str = DEFAULT_SYMBOL, db: str = None) -> bool:
    if not data or "records" not in data:
        return False

    if db is None:
        db = str(DB)

    ts = datetime.now().isoformat()
    records = data.get("records", {})
    expiry = records.get("expiryDates", [""])[0]
    strike_data = records.get("data", [])
    spot = records.get("underlyingValue", 0) or 0

    conn = sqlite3.connect(db)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, symbol TEXT NOT NULL, expiry TEXT NOT NULL,
            spot REAL,
            strike REAL NOT NULL, option_type TEXT NOT NULL,
            oi INTEGER DEFAULT 0, change_oi INTEGER DEFAULT 0,
            volume INTEGER DEFAULT 0, iv REAL, ltp REAL, change REAL,
            bid REAL, ask REAL,
            UNIQUE(timestamp, symbol, expiry, strike, option_type)
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON snapshots(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sym ON snapshots(symbol)")

    saved = 0
    for row in strike_data:
        strike = row.get("strikePrice", 0)
        if not strike:
            continue
        for opt in ["CE", "PE"]:
            if opt not in row:
                continue
            o = row[opt]
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO snapshots
                    (timestamp, symbol, expiry, spot, strike, option_type, oi, change_oi, volume, iv, ltp, change, bid, ask)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (ts, symbol, expiry, spot, strike, opt,
                    o.get("openInterest", 0), o.get("changeinOpenInterest", 0),
                    o.get("totalTradedVolume", 0), o.get("impliedVolatility"),
                    o.get("lastPrice"), o.get("change"),
                    o.get("bidprice"), o.get("askPrice")))
                saved += 1
            except sqlite3.Error:
                pass

    conn.commit()
    conn.close()
    return saved > 0


def load_latest(symbol: str = DEFAULT_SYMBOL, db: str = None) -> Optional[dict]:
    if db is None:
        db = str(DB)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT timestamp, expiry, spot FROM snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    if not row:
        conn.close()
        return None

    ts, expiry, spot = row
    rows = conn.execute(
        "SELECT strike, option_type, oi, change_oi, volume, iv, ltp, change, bid, ask "
        "FROM snapshots WHERE symbol = ? AND timestamp = ? ORDER BY strike",
        (symbol, ts)
    ).fetchall()
    conn.close()

    by_strike = {}
    for r in rows:
        s, opt, oi, coi, vol, iv, ltp, chg, bid, ask = r
        if s not in by_strike:
            by_strike[s] = {}
        by_strike[s][opt] = {
            "oi": oi, "change_oi": coi, "volume": vol,
            "iv": iv, "ltp": ltp, "change": chg, "bid": bid, "ask": ask
        }

    return {"timestamp": ts, "expiry": expiry, "spot": spot, "strikes": by_strike}


def load_previous(symbol: str = DEFAULT_SYMBOL, db: str = None) -> Optional[dict]:
    if db is None:
        db = str(DB)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT DISTINCT timestamp FROM snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 2",
        (symbol,)
    ).fetchall()
    if len(row) < 2:
        conn.close()
        return None

    ts = row[1][0]
    rows = conn.execute(
        "SELECT strike, option_type, oi, change_oi FROM snapshots WHERE symbol = ? AND timestamp = ?",
        (symbol, ts)
    ).fetchall()
    conn.close()

    data = {}
    for r in rows:
        s, opt, oi, coi = r
        if s not in data:
            data[s] = {}
        data[s][opt] = {"oi": oi, "change_oi": coi}
    return {"timestamp": ts, "strikes": data}


if __name__ == "__main__":
    d = fetch("NIFTY")
    if d:
        n = persist(d, "NIFTY")
        print(f"Fetched and persisted {n} records")
    else:
        print("Fetch failed — check market hours")