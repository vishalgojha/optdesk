#!/usr/bin/env python3
"""NSE Option Chain Poller via nsepython"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import sqlite3
import time
from datetime import datetime, time as dtime

try:
    import nsepython
    HAS_NSE = True
except ImportError:
    HAS_NSE = False

DEFAULT_SYMBOL = "NIFTY"


def fetch_via_nsepython(symbol: str = DEFAULT_SYMBOL) -> dict | None:
    """Fetch using nsepython library"""
    if not HAS_NSE:
        return None

    print(f"📡 Fetching via nsepython...")

    try:
        data = nsepython.option_chain(symbol)
        if data:
            if isinstance(data, list):
                data = data[0]
            if "records" in data or "data" in data:
                print(f"  ✅ Got data via option_chain")
                return data
    except Exception as e:
        print(f"  option_chain error: {e}")

    try:
        data = nsepython.nse_optionchain_scrapper(symbol)
        if data:
            print(f"  ✅ Got data via scrapper")
            return data
    except Exception as e:
        print(f"  nse_optionchain_scrapper error: {e}")

    try:
        data = nsepython.oi_chain_builder(symbol)
        if data:
            print(f"  ✅ Got data via oi_chain_builder")
            return data
    except Exception as e:
        print(f"  oi_chain_builder error: {e}")

    return None


def save_to_sqlite(data: dict, symbol: str = DEFAULT_SYMBOL, db: str = "optionchain.db") -> bool:
    if not data or "records" not in data:
        print("❌ No valid data to save")
        return False

    ts = datetime.now().isoformat()
    records = data.get("records", {})
    expiry = records.get("expiryDates", [""])[0]
    strike_data = records.get("data", [])

    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, symbol TEXT NOT NULL, expiry TEXT NOT NULL,
            strike REAL NOT NULL, option_type TEXT NOT NULL,
            oi INTEGER DEFAULT 0, change_oi INTEGER DEFAULT 0, volume INTEGER DEFAULT 0,
            iv REAL, ltp REAL, change REAL, bid REAL, ask REAL,
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
                    (timestamp, symbol, expiry, strike, option_type, oi, change_oi, volume, iv, ltp, change, bid, ask)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (ts, symbol, expiry, strike, opt,
                    o.get("openInterest", 0), o.get("changeinOpenInterest", 0), o.get("totalTradedVolume", 0),
                    o.get("impliedVolatility"), o.get("lastPrice"), o.get("change"),
                    o.get("bidprice"), o.get("askPrice")))
                saved += 1
            except sqlite3.Error:
                pass

    conn.commit()
    conn.close()
    print(f"✅ Saved {saved} records to {db}")
    return True


def export_csv(db: str = "optionchain.db", symbol: str = DEFAULT_SYMBOL) -> str | None:
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT timestamp FROM snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if not row:
        conn.close()
        return None

    latest_ts = row[0]
    rows = conn.execute("SELECT strike, option_type, oi, change_oi, volume, iv, ltp, change, bid, ask FROM snapshots WHERE symbol = ? AND timestamp = ? ORDER BY strike, option_type", (symbol, latest_ts)).fetchall()
    conn.close()

    if not rows:
        return None

    by_strike = {}
    for r in rows:
        s, opt, oi, coi, vol, iv, ltp, chg, bid, ask = r
        if s not in by_strike:
            by_strike[s] = {"CE": [], "PE": []}
        by_strike[s][opt] = [oi, coi, vol, iv, ltp, chg, bid, ask]

    lines = []
    for strike in sorted(by_strike.keys()):
        ce = by_strike[strike].get("CE", [0]*8)
        pe = by_strike[strike].get("PE", [0]*8)
        ce_s = ",".join(str(v) if v else "" for v in ce[:7])
        pe_s = ",".join(str(v) if v else "" for v in pe[:7])
        lines.append(f"{ce_s},{strike},{pe_s}")

    with open("option-chain.csv", "w") as f:
        f.write("CALLS,Strike,PUTS\nOI,Chg OI,Volume,IV,LTP,Chg,Bid,Ask,Strike,OI,Chg OI,Volume,IV,LTP,Chg,Bid,Ask\n")
        f.write("\n".join(lines))

    print("✅ Exported option-chain.csv")
    return "option-chain.csv"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--db", default="optionchain.db")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*50}")
    print(f"  NSE Poller | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    now = datetime.now().time()
    if not args.force and not (dtime(9, 15) <= now <= dtime(15, 30)):
        print(f"⚠️  Market closed ({now.strftime('%H:%M')}). Skipping.")
        if not args.export:
            sys.exit(0)

    data = fetch_via_nsepython(args.symbol)

    if data:
        save_to_sqlite(data, args.symbol, args.db)

        records = data.get("records", {})
        print(f"\n  Spot: {records.get('underlyingValue', 'N/A')}")
        print(f"  Expiries: {records.get('expiryDates', [])[:3]}")

        # Save signal record
        ts = datetime.now().isoformat()
        conn2 = sqlite3.connect(args.db)
        conn2.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal TEXT,
                confidence TEXT,
                pcr_total REAL,
                atm REAL,
                max_pain REAL,
                signal_json TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        conn2.execute("""
            INSERT OR IGNORE INTO signals (timestamp, symbol)
            VALUES (?, ?)
        """, (ts, args.symbol))
        conn2.close()

        if args.export:
            export_csv(args.db, args.symbol)
    else:
        print("❌ Fetch failed")
        sys.exit(1)