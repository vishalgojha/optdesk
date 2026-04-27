#!/usr/bin/env python3
"""
Enhanced Option Chain Analytics
Includes: IV Skew, Greeks, Historical Charts Data
"""

import sqlite3
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB = Path(__file__).parent / "option_intel.db"


# ── Black-Scholes Greeks ──────────────────────────────────────────────────

def normal_cdf(x: float) -> float:
    """Cumulative distribution function"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def normal_pdf(x: float) -> float:
    """Probability density function"""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> dict:
    """
    Calculate Black-Scholes Greeks
    S: Spot price, K: Strike, T: Time to expiry (years), r: Risk-free rate, sigma: IV
    """
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0, "price": 0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type.lower() == "call":
        delta = normal_cdf(d1)
        theta = (-S * normal_pdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * normal_cdf(d2)) / 365
        rho = K * T * math.exp(-r * T) * normal_cdf(d2) / 100
    else:
        delta = normal_cdf(d1) - 1
        theta = (-S * normal_pdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * normal_cdf(-d2)) / 365
        rho = -K * T * math.exp(-r * T) * normal_cdf(-d2) / 100

    gamma = normal_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * math.sqrt(T) * normal_pdf(d1) / 100

    price = S * normal_cdf(d1) - K * math.exp(-r * T) * normal_cdf(d2) if option_type.lower() == "call" else K * math.exp(-r * T) * normal_cdf(-d2) - S * normal_cdf(-d1)

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
        "price": round(price, 2)
    }


def calculate_all_greeks(rows: list, spot: float, T: float = 30/365, r: float = 0.065) -> list:
    """Calculate Greeks for all strikes"""
    for row in rows:
        ce_iv = row.get("ce_iv", 0) or 0
        pe_iv = row.get("pe_iv", 0) or 0

        if ce_iv > 0:
            ce_greeks = black_scholes(spot, row["strike"], T, r, ce_iv / 100, "call")
            row["ce_delta"] = ce_greeks["delta"]
            row["ce_gamma"] = ce_greeks["gamma"]
            row["ce_theta"] = ce_greeks["theta"]
            row["ce_vega"] = ce_greeks["vega"]

        if pe_iv > 0:
            pe_greeks = black_scholes(spot, row["strike"], T, r, pe_iv / 100, "put")
            row["pe_delta"] = pe_greeks["delta"]
            row["pe_gamma"] = pe_greeks["gamma"]
            row["pe_theta"] = pe_greeks["theta"]
            row["pe_vega"] = pe_greeks["vega"]

    return rows


# ── IV Skew Analysis ───────────────────────────────────────────────────

def calculate_iv_skew(rows: list, atm: float) -> dict:
    """Calculate IV skew: difference between OTM call and OTM put IV"""
    otm_calls = [r for r in rows if r.get("strike", 0) > atm and r.get("ce_iv")]
    otm_puts = [r for r in rows if r.get("strike", 0) < atm and r.get("pe_iv")]

    avg_ce_iv = sum(r["ce_iv"] for r in otm_calls) / len(otm_calls) if otm_calls else 0
    avg_pe_iv = sum(r["pe_iv"] for r in otm_puts) / len(otm_puts) if otm_puts else 0

    skew = avg_pe_iv - avg_ce_iv

    return {
        "iv_skew": round(skew, 2),
        "avg_otm_call_iv": round(avg_ce_iv, 2),
        "avg_otm_put_iv": round(avg_pe_iv, 2),
        "interpretation": "FEAR (high put IV)" if skew > 3 else "BULLISH (high call IV)" if skew < -3 else "BALANCED"
    }


# ── Support/Resistance Levels ─────────────────────────────────────────

def find_support_resistance(rows: list, top_n: int = 5) -> dict:
    """Find key support/resistance based on OI concentration"""
    ce_oi_by_strike = [(r["strike"], r.get("ce_oi", 0)) for r in rows if r.get("ce_oi")]
    pe_oi_by_strike = [(r["strike"], r.get("pe_oi", 0)) for r in rows if r.get("pe_oi")]

    ce_oi_by_strike.sort(key=lambda x: x[1], reverse=True)
    pe_oi_by_strike.sort(key=lambda x: x[1], reverse=True)

    resistance = [{"strike": s, "oi": oi} for s, oi in ce_oi_by_strike[:top_n]]
    support = [{"strike": s, "oi": oi} for s, oi in pe_oi_by_strike[:top_n]]

    return {"resistance": resistance, "support": support}


# ── OI Buildup Analysis ────────────────────────────────────────────────

def analyze_oi_buildup(rows: list) -> dict:
    """Analyze OI buildup and unwinding"""
    ce_buildup = sorted(
        [r for r in rows if r.get("ce_chng_oi", 0) > 0],
        key=lambda x: x.get("ce_chng_oi", 0),
        reverse=True
    )[:5]

    pe_buildup = sorted(
        [r for r in rows if r.get("pe_chng_oi", 0) > 0],
        key=lambda x: x.get("pe_chng_oi", 0),
        reverse=True
    )[:5]

    ce_unwind = sorted(
        [r for r in rows if r.get("ce_chng_oi", 0) < 0],
        key=lambda x: x.get("ce_chng_oi", 0)
    )[:5]

    pe_unwind = sorted(
        [r for r in rows if r.get("pe_chng_oi", 0) < 0],
        key=lambda x: x.get("pe_chng_oi", 0)
    )[:5]

    return {
        "ce_buildup": [{"strike": r["strike"], "change_oi": r.get("ce_chng_oi", 0)} for r in ce_buildup],
        "pe_buildup": [{"strike": r["strike"], "change_oi": r.get("pe_chng_oi", 0)} for r in pe_buildup],
        "ce_unwind": [{"strike": r["strike"], "change_oi": r.get("ce_chng_oi", 0)} for r in ce_unwind],
        "pe_unwind": [{"strike": r["strike"], "change_oi": r.get("pe_chng_oi", 0)} for r in pe_unwind],
    }


# ── Historical Data for Charts ─────────────────────────────────────────

def get_historical_pcr(symbol: str, days: int = 30) -> list:
    """Get PCR history for charting"""
    conn = sqlite3.connect(DB)
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(timestamp) as date, pcr_total, signal, atm, max_pain
        FROM daily_snapshots
        WHERE symbol = ? AND timestamp > ?
        ORDER BY date
    """, (symbol, since)).fetchall()
    conn.close()
    return [{"date": r[0], "pcr": r[1], "signal": r[2], "atm": r[3], "max_pain": r[4]} for r in rows]


def get_historical_oi(symbol: str, days: int = 30) -> list:
    """Get total OI history"""
    conn = sqlite3.connect(DB)
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT DATE(timestamp) as date, total_ce_oi, total_pe_oi
        FROM daily_snapshots
        WHERE symbol = ? AND timestamp > ?
        ORDER BY date
    """, (symbol, since)).fetchall()
    conn.close()
    return [{"date": r[0], "ce_oi": r[1], "pe_oi": r[2]} for r in rows]


def get_oi_heatmap(symbol: str, days: int = 30) -> list:
    """Get OI distribution heatmap by strike ranges"""
    conn = sqlite3.connect(DB)
    since = (datetime.now() - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT strike, AVG(oi) as avg_oi
        FROM strike_data
        WHERE symbol = ? AND timestamp > ? AND option_type = 'CE'
        GROUP BY ROUND(strike/500)*500
        ORDER BY strike
    """, (symbol, since)).fetchall()

    conn.close()
    return [{"strike_range": f"{r[0]-250}-{r[0]+250}", "avg_ce_oi": r[1]} for r in rows]


# ── Max Pain Accuracy ───────────────────────────────────────────────────

def max_pain_accuracy(symbol: str, days: int = 90) -> dict:
    """Analyze how often spot closes near max pain"""
    conn = sqlite3.connect(DB)
    since = (datetime.now() - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT atm, max_pain FROM daily_snapshots
        WHERE symbol = ? AND timestamp > ?
    """, (symbol, since)).fetchall()

    conn.close()

    if not rows:
        return {"accuracy": 0, "samples": 0}

    within_25 = sum(1 for r in rows if r[0] and r[1] and abs(r[0] - r[1]) <= 25)
    within_50 = sum(1 for r in rows if r[0] and r[1] and abs(r[0] - r[1]) <= 50)
    within_100 = sum(1 for r in rows if r[0] and r[1] and abs(r[0] - r[1]) <= 100)

    total = len(rows)
    return {
        "accuracy_25pts": round(within_25 / total * 100, 1),
        "accuracy_50pts": round(within_50 / total * 100, 1),
        "accuracy_100pts": round(within_100 / total * 100, 1),
        "samples": total
    }


# ── Signal Change Detection ────────────────────────────────────────────

def detect_signal_change(symbol: str) -> Optional[dict]:
    """Detect signal changes from previous day"""
    conn = sqlite3.connect(DB)

    latest = conn.execute("""
        SELECT timestamp, signal, pcr_total FROM daily_snapshots
        WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1
    """, (symbol,)).fetchone()

    if not latest:
        conn.close()
        return None

    prev = conn.execute("""
        SELECT timestamp, signal, pcr_total FROM daily_snapshots
        WHERE symbol = ? AND timestamp < ? ORDER BY timestamp DESC LIMIT 1
    """, (symbol, latest[0])).fetchone()

    conn.close()

    if not prev:
        return None

    changed = latest[1] != prev[1]
    pcr_change = round(latest[2] - prev[2], 3) if latest[2] and prev[2] else 0

    return {
        "signal_changed": changed,
        "previous_signal": prev[1],
        "current_signal": latest[1],
        "pcr_change": pcr_change,
        "alert": changed
    }


# ── Composite Score ───────────────────────────────────────────────────

def calculate_composite_score(symbol: str) -> dict:
    """Calculate a composite sentiment score"""
    conn = sqlite3.connect(DB)
    row = conn.execute("""
        SELECT pcr_total, pcr_near_atm, ce_buildup, pe_buildup
        FROM daily_snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1
    """, (symbol,)).fetchone()
    conn.close()

    if not row:
        return {"score": 50, "sentiment": "NEUTRAL"}

    pcr, near_pcr, ce_bup, pe_bup = row

    score = 50

    # PCR contribution (max 25 points)
    if pcr:
        if pcr > 1.5: score += 25
        elif pcr > 1.2: score += 15
        elif pcr > 1.0: score += 5
        elif pcr < 0.5: score -= 25
        elif pcr < 0.8: score -= 15
        else: score -= 5

    # OI buildup contribution (max 15 points each)
    if pe_bup and ce_bup:
        if pe_bup > ce_bup * 1.5: score += 15
        elif ce_bup > pe_bup * 1.5: score -= 15

    score = max(0, min(100, score))

    sentiment = "STRONG BULLISH" if score > 75 else "BULLISH" if score > 60 else "SLIGHTLY BULLISH" if score > 55 else "NEUTRAL" if score > 45 else "SLIGHTLY BEARISH" if score > 40 else "BEARISH" if score > 25 else "STRONG BEARISH"

    return {"score": score, "sentiment": sentiment}


if __name__ == "__main__":
    # Test
    rows = [
        {"strike": 24000, "ce_iv": 15.5, "pe_iv": 18.2, "ce_oi": 500000, "pe_oi": 600000, "ce_chng_oi": 50000, "pe_chng_oi": -20000},
        {"strike": 24100, "ce_iv": 14.2, "pe_iv": 17.8, "ce_oi": 450000, "pe_oi": 550000, "ce_chng_oi": -10000, "pe_chng_oi": 30000},
    ]
    skew = calculate_iv_skew(rows, 24050)
    print("IV Skew:", skew)

    greeks = calculate_all_greeks(rows, 24050)
    print("Greeks:", greeks[0])
