#!/usr/bin/env python3
"""
NSE Option Chain Intelligence - Data Collection
Uses nsepython to collect data during market hours
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import sqlite3
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import nsepython
    HAS_NSE = True
except ImportError:
    HAS_NSE = False

DB = Path(__file__).parent / "option_intel.db"


def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            expiry TEXT NOT NULL,
            spot REAL,
            atm REAL,
            max_pain REAL,
            pcr_total REAL,
            pcr_near_atm REAL,
            total_ce_oi INTEGER,
            total_pe_oi INTEGER,
            top_ce_oi INTEGER,
            top_ce_strike REAL,
            top_pe_oi INTEGER,
            top_pe_strike REAL,
            ce_buildup INTEGER,
            pe_buildup INTEGER,
            signal TEXT,
            UNIQUE(timestamp, symbol, expiry)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strike_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            expiry TEXT NOT NULL,
            strike REAL NOT NULL,
            option_type TEXT NOT NULL,
            oi INTEGER DEFAULT 0,
            change_oi INTEGER DEFAULT 0,
            volume INTEGER DEFAULT 0,
            iv REAL,
            ltp REAL,
            UNIQUE(timestamp, symbol, expiry, strike, option_type)
        )
    """)
    conn.commit()
    conn.close()


def fetch_data(symbol: str):
    if not HAS_NSE:
        return None

    try:
        data = nsepython.option_chain(symbol)
        if data and ("records" in data or "filtered" in data):
            return data
    except Exception as e:
        print(f"  nsepython error: {e}")

    try:
        data = nsepython.nse_optionchain_scrapper(symbol)
        if data:
            return data
    except Exception as e:
        print(f"  scrapper error: {e}")

    return None


def compute_metrics(records: list, spot: float) -> dict:
    if not records:
        return {}

    rows = []
    for r in records:
        strike = r.get("strikePrice", 0)
        if not strike:
            continue
        ce = r.get("CE", {})
        pe = r.get("PE", {})
        rows.append({
            "strike": float(strike),
            "ce_oi": int(ce.get("openInterest", 0) or 0),
            "ce_chng_oi": int(ce.get("changeinOpenInterest", 0) or 0),
            "ce_vol": int(ce.get("totalTradedVolume", 0) or 0),
            "ce_iv": ce.get("impliedVolatility"),
            "ce_ltp": ce.get("lastPrice"),
            "pe_oi": int(pe.get("openInterest", 0) or 0),
            "pe_chng_oi": int(pe.get("changeinOpenInterest", 0) or 0),
            "pe_vol": int(pe.get("totalTradedVolume", 0) or 0),
            "pe_iv": pe.get("impliedVolatility"),
            "pe_ltp": pe.get("lastPrice"),
        })

    total_ce = sum(r["ce_oi"] for r in rows)
    total_pe = sum(r["pe_oi"] for r in rows)
    pcr = round(total_pe / total_ce, 3) if total_ce > 0 else 0

    valid = [r for r in rows if r["ce_ltp"] and r["pe_ltp"]]
    atm = min(valid, key=lambda x: abs(x["ce_ltp"] - x["pe_ltp"]))["strike"] if valid else rows[len(rows)//2]["strike"]

    strikes = [r["strike"] for r in rows]
    min_pain, mp_strike = float("inf"), atm
    for s in strikes:
        ce_loss = sum(max(0, s - r["strike"]) * r["ce_oi"] for r in rows)
        pe_loss = sum(max(0, r["strike"] - s) * r["pe_oi"] for r in rows)
        t = ce_loss + pe_loss
        if t < min_pain:
            min_pain = t
            mp_strike = s

    near = [r for r in rows if abs(r["strike"] - atm) <= 500]
    near_ce = sum(r["ce_oi"] for r in near)
    near_pe = sum(r["pe_oi"] for r in near)
    near_pcr = round(near_pe / near_ce, 3) if near_ce > 0 else 0

    top_ce = sorted(rows, key=lambda x: x["ce_oi"], reverse=True)[:1]
    top_pe = sorted(rows, key=lambda x: x["pe_oi"], reverse=True)[:1]
    ce_bup = sum(r["ce_chng_oi"] for r in rows if r["ce_chng_oi"] > 0)
    pe_bup = sum(r["pe_chng_oi"] for r in rows if r["pe_chng_oi"] > 0)

    signal = "BULLISH" if pcr > 1.2 else "BEARISH" if pcr < 0.8 else "NEUTRAL"

    return {
        "spot": spot,
        "atm": atm,
        "max_pain": mp_strike,
        "pcr_total": pcr,
        "pcr_near_atm": near_pcr,
        "total_ce_oi": total_ce,
        "total_pe_oi": total_pe,
        "top_ce_oi": top_ce[0]["ce_oi"] if top_ce else 0,
        "top_ce_strike": top_ce[0]["strike"] if top_ce else 0,
        "top_pe_oi": top_pe[0]["pe_oi"] if top_pe else 0,
        "top_pe_strike": top_pe[0]["strike"] if top_pe else 0,
        "ce_buildup": ce_bup,
        "pe_buildup": pe_bup,
        "signal": signal,
        "rows": rows,
    }


def save_snapshot(ts: str, symbol: str, expiry: str, m: dict):
    conn = sqlite3.connect(DB)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO daily_snapshots
            (timestamp, symbol, expiry, spot, atm, max_pain, pcr_total, pcr_near_atm,
             total_ce_oi, total_pe_oi, top_ce_oi, top_ce_strike, top_pe_oi, top_pe_strike,
             ce_buildup, pe_buildup, signal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (ts, symbol, expiry, m.get("spot"), m.get("atm"), m.get("max_pain"),
            m.get("pcr_total"), m.get("pcr_near_atm"), m.get("total_ce_oi"), m.get("total_pe_oi"),
            m.get("top_ce_oi"), m.get("top_ce_strike"), m.get("top_pe_oi"), m.get("top_pe_strike"),
            m.get("ce_buildup"), m.get("pe_buildup"), m.get("signal")))

        for r in m.get("rows", []):
            for opt, oi, coi, vol, iv, ltp in [
                ("CE", r["ce_oi"], r["ce_chng_oi"], r["ce_vol"], r["ce_iv"], r["ce_ltp"]),
                ("PE", r["pe_oi"], r["pe_chng_oi"], r["pe_vol"], r["pe_iv"], r["pe_ltp"]),
            ]:
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO strike_data
                        (timestamp, symbol, expiry, strike, option_type, oi, change_oi, volume, iv, ltp)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (ts, symbol, expiry, r["strike"], opt, oi, coi, vol, iv, ltp))
                except sqlite3.Error:
                    pass

        conn.commit()
        print(f"  ✅ {symbol} {expiry} — ATM {m.get('atm'):.0f} PCR {m.get('pcr_total')} {m.get('signal')}")
    except sqlite3.Error as e:
        print(f"  DB error: {e}")
    finally:
        conn.close()


def scrape_symbol(symbol: str, force: bool = False):
    print(f"\n{'─'*50}")
    print(f"  {symbol}")
    print(f"{'─'*50}")

    if not HAS_NSE:
        print("  ❌ nsepython not installed: pip install nsepython")
        return False

    ts = datetime.now().isoformat()
    conn = sqlite3.connect(DB)
    exists = conn.execute(
        "SELECT COUNT(*) FROM daily_snapshots WHERE symbol=? AND timestamp>?",
        (symbol, (datetime.now() - timedelta(hours=4)).isoformat())
    ).fetchone()[0]
    conn.close()

    if exists and not force:
        print(f"  ⏭️  Recent data exists (use --force to re-scrape)")
        return True

    data = fetch_data(symbol)
    if not data:
        print(f"  ❌ No data from nsepython")
        return False

    records = data.get("records", {}).get("data", [])
    if not records:
        records = data.get("filtered", {}).get("data", [])

    spot = data.get("records", {}).get("underlyingValue")
    expiry = data.get("records", {}).get("expiryDates", [""])[0]

    metrics = compute_metrics(records, spot)
    save_snapshot(ts, symbol, expiry, metrics)
    return True


def analyze(symbol: str, days: int = 90):
    conn = sqlite3.connect(DB)
    since = (datetime.now() - timedelta(days=days)).isoformat()

    count = conn.execute(
        "SELECT COUNT(*) FROM daily_snapshots WHERE symbol=? AND timestamp>?", (symbol, since)
    ).fetchone()[0]

    if count == 0:
        conn.close()
        return {"symbol": symbol, "data_points": 0}

    pcr_rows = conn.execute("""
        SELECT DATE(timestamp) as day, AVG(pcr_total) as ap FROM daily_snapshots
        WHERE symbol=? AND timestamp>? GROUP BY day ORDER BY day
    """, (symbol, since)).fetchall()

    signal_rows = conn.execute("""
        SELECT signal, COUNT(*) FROM daily_snapshots WHERE symbol=? AND timestamp>? GROUP BY signal
    """, (symbol, since)).fetchall()

    top_ce = conn.execute("""
        SELECT ROUND(top_ce_strike/100)*100 as s, COUNT(*) as c FROM daily_snapshots
        WHERE symbol=? AND timestamp>? AND top_ce_strike>0 GROUP BY s ORDER BY c DESC LIMIT 5
    """, (symbol, since)).fetchall()

    top_pe = conn.execute("""
        SELECT ROUND(top_pe_strike/100)*100 as s, COUNT(*) as c FROM daily_snapshots
        WHERE symbol=? AND timestamp>? AND top_pe_strike>0 GROUP BY s ORDER BY c DESC LIMIT 5
    """, (symbol, since)).fetchall()

    pcr_stats = conn.execute("""
        SELECT MIN(pcr_total), MAX(pcr_total), AVG(pcr_total) FROM daily_snapshots WHERE symbol=? AND timestamp>?
    """, (symbol, since)).fetchone()

    mp_rows = conn.execute("SELECT atm, max_pain FROM daily_snapshots WHERE symbol=? AND timestamp>?", (symbol, since)).fetchall()

    buildup = conn.execute("""
        SELECT signal, AVG(ce_buildup) as ace, AVG(pe_buildup) as ape FROM daily_snapshots WHERE symbol=? AND timestamp>? GROUP BY signal
    """, (symbol, since)).fetchall()

    conn.close()

    avg_pcr = pcr_stats[2] if pcr_stats else 0
    total = sum(r[1] for r in signal_rows)
    sig_dist = {r[0]: round(r[1]/total*100, 1) if total else 0 for r in signal_rows}

    near_mp = sum(1 for r in mp_rows if r[0] and r[1] and abs(r[0]-r[1]) < 100)
    mp_acc = round(near_mp/len(mp_rows)*100, 1) if mp_rows else 0

    return {
        "symbol": symbol,
        "period_days": days,
        "data_points": count,
        "avg_pcr": round(avg_pcr, 3),
        "pcr_min": round(pcr_stats[0], 3) if pcr_stats else 0,
        "pcr_max": round(pcr_stats[1], 3) if pcr_stats else 0,
        "pcr_trend": "BULLISH BIAS" if avg_pcr > 1.1 else "BEARISH BIAS" if avg_pcr < 0.9 else "BALANCED",
        "signal_distribution": sig_dist,
        "max_pain_accuracy": f"{mp_acc}% within 100pts",
        "key_ce_strikes": [str(int(r[0])) for r in top_ce],
        "key_pe_strikes": [str(int(r[0])) for r in top_pe],
        "pcr_daily": [{"date": r[0], "pcr": round(r[1], 3)} for r in pcr_rows[-30:]],
        "buildup": [{"signal": r[0], "avg_ce": int(r[1]), "avg_pe": int(r[2])} for r in buildup],
    }


def print_report(r: dict):
    print(f"\n{'='*60}")
    print(f"  📊 {r['symbol']} Intelligence ({r['period_days']} days)")
    print(f"{'='*60}")
    print(f"  Data points  : {r['data_points']}")
    print(f"  Avg PCR      : {r['avg_pcr']} (range: {r['pcr_min']}–{r['pcr_max']})")
    print(f"  Bias        : {r['pcr_trend']}")
    print(f"  Max Pain Acc: {r['max_pain_accuracy']}")

    print(f"\n  Signal Distribution:")
    for sig in ["BULLISH", "BEARISH", "NEUTRAL"]:
        pct = r["signal_distribution"].get(sig, 0)
        bar = "█" * int(pct / 2)
        emoji = "🟢" if sig == "BULLISH" else "🔴" if sig == "BEARISH" else "🟡"
        print(f"    {emoji} {sig:10} {pct:5.1f}% {bar}")

    print(f"\n  Key CE Strikes (resistance):")
    for s in r.get("key_ce_strikes", []):
        print(f"    🚧 {s}")

    print(f"\n  Key PE Strikes (support):")
    for s in r.get("key_pe_strikes", []):
        print(f"    🛡️  {s}")

    print(f"\n  Recent PCR:")
    for d in r.get("pcr_daily", [])[-10:]:
        bar = "█" * int(d["pcr"] * 5)
        emoji = "🟢" if d["pcr"] > 1.2 else "🔴" if d["pcr"] < 0.8 else "🟡"
        print(f"    {d['date']} {emoji} {d['pcr']:.3f} {bar}")

    print(f"\n  OI Buildup by Signal:")
    for bp in r.get("buildup", []):
        print(f"    {bp['signal']:10} CE: {bp['avg_ce']:>10,} | PE: {bp['avg_pe']:>10,}")
    print("="*60 + "\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="NIFTY,BANKNIFTY")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--scrape", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    init_db()

    if args.scrape or (not args.analyze):
        for sym in symbols:
            scrape_symbol(sym, args.force)
            time.sleep(2)

    if args.analyze or args.days:
        for sym in symbols:
            report = analyze(sym, args.days)
            if report["data_points"] > 0:
                print_report(report)
            else:
                print(f"\n⚠️  No data for {sym}. Run with --scrape during market hours.")