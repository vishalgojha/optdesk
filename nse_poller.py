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
POLL_INTERVAL = 300


def get_sgx_nifty() -> float | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEMDCP50?interval=5m&range=1d",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            quotes = data["chart"]["result"][0]["meta"]["chartingUntil"]
            return None
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://query2.finance.yahoo.com/v8/finance/chart/NSEMDCP50?interval=5m&range=1d",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            return float(meta.get("regularMarketPrice", 0)) or None
    except Exception:
        return None


def is_market_open() -> bool:
    now = datetime.now().time()
    return dtime(9, 15) <= now <= dtime(15, 30)


def is_pre_market() -> bool:
    now = datetime.now().time()
    return dtime(9, 0) <= now <= dtime(9, 15)


def poll_once(symbol: str = DEFAULT_SYMBOL, db: str = "optionchain.db") -> bool:
    print(f"\n{'='*50}")
    print(f"  Poll at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    sgx = get_sgx_nifty()
    if sgx:
        print(f"  📈 SGX Nifty: {sgx}")

    if not is_market_open():
        if is_pre_market():
            print("  ⏳ Pre-market — polling anyway")
        else:
            print(f"  ⚠️  Market closed ({datetime.now().time().strftime('%H:%M')}). Sleeping.")
            return False

    data = fetch_via_nsepython(symbol)

    if data:
        save_to_sqlite(data, args.symbol, args.db)
        records = data.get("records", {})
        print(f"  Spot: {records.get('underlyingValue', 'N/A')}")
        sig = save_signal_record(data, args.symbol, args.db)
        print(f"  Signal: {sig.get('signal')} ({sig.get('confidence')})")
        if args.export:
            export_csv(args.db, args.symbol)
        return True
    else:
        print("  ❌ Fetch failed — retrying next cycle...")
        return False
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


def save_signal_record(data: dict, symbol: str, db: str):
    from nse_signal import compute_signal
    from analytics import calculate_composite_score, detect_signal_change

    records = data.get("records", {})
    spot = records.get("underlyingValue", 0) or 0
    expiry = records.get("expiryDates", [""])[0]
    strike_data = records.get("data", [])

    by_strike = {}
    for row in strike_data:
        strike = row.get("strikePrice", 0)
        if not strike:
            continue
        by_strike[strike] = {
            "ce_oi": row.get("CE", {}).get("openInterest", 0),
            "pe_oi": row.get("PE", {}).get("openInterest", 0),
            "ce_chng_oi": row.get("CE", {}).get("changeinOpenInterest", 0),
            "pe_chng_oi": row.get("PE", {}).get("changeinOpenInterest", 0),
            "ce_iv": row.get("CE", {}).get("impliedVolatility", 0),
            "pe_iv": row.get("PE", {}).get("impliedVolatility", 0),
            "ce_ltp": row.get("CE", {}).get("lastPrice", 0),
            "pe_ltp": row.get("PE", {}).get("lastPrice", 0),
        }

    pcr_total = sum(r["pe_oi"] for r in by_strike.values()) / max(1, sum(r["ce_oi"] for r in by_strike.values()))
    atm_strike = min(by_strike.keys(), key=lambda s: abs(s - spot)) if by_strike else 0

    ts = datetime.now().isoformat()
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, symbol TEXT NOT NULL,
            signal TEXT, confidence TEXT,
            pcr_total REAL, atm REAL, max_pain REAL,
            score REAL, sentiment TEXT,
            signal_json TEXT,
            UNIQUE(symbol, timestamp)
        )
    """)

    signal_data = compute_signal(by_strike, spot, atm_strike, pcr_total)
    sig_json = json.dumps(signal_data)
    score_data = calculate_composite_score(symbol)
    change = detect_signal_change(symbol)

    conn.execute("""
        INSERT OR REPLACE INTO signals
        (timestamp, symbol, signal, confidence, pcr_total, atm, max_pain, score, sentiment, signal_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, symbol, signal_data.get("signal"), signal_data.get("confidence"),
          pcr_total, atm_strike, signal_data.get("max_pain"),
          score_data.get("score"), score_data.get("sentiment"), sig_json))

    conn.commit()
    conn.close()

    if change and change.get("alert"):
        from notifications import notify_signal
        print("  🔔 Signal changed! Sending notifications...")
        notify_signal(signal_data)

    return signal_data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--db", default="optionchain.db")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-force", dest="force", action="store_false")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL)
    args = parser.parse_args()

    if args.daemon:
        print(f"\n🔄 Auto-scheduler mode — polling every {args.interval}s during market hours")
        print("   Ctrl+C to stop\n")
        while True:
            if is_market_open():
                success = poll_once(args.symbol, args.db)
                if not success:
                    time.sleep(args.interval)
                else:
                    time.sleep(args.interval)
            elif is_pre_market():
                print(f"  ⏳ Pre-market — polling every {args.interval}s")
                time.sleep(args.interval // 4)
            else:
                sleep_until = 9 * 60 + 15
                now_mins = datetime.now().hour * 60 + datetime.now().minute
                if now_mins >= 15 * 60:
                    sleep_until = (24 + 9) * 60 + 15
                sleep_mins = sleep_until - now_mins
                print(f"  💤 Market closed — sleeping {sleep_mins}min until 09:15")
                time.sleep(min(sleep_mins * 60, args.interval * 4))
    else:
        poll_once(args.symbol, args.db)