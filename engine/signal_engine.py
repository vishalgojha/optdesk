#!/usr/bin/env python3
"""
Signal Engine - 3-layer decision system
Layer 1: Market Bias (from option chain)
Layer 2: Key Levels (resistance/support)
Layer 3: Trigger Engine (price + OI change combined)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .analyzer import analyze, compute_bias
from .data_fetcher import load_latest, load_previous


DB = Path(__file__).parent.parent / "optionchain.db"


def get_signal(symbol: str = "NIFTY") -> dict:
    data = load_latest(symbol)
    prev_data = load_previous(symbol)

    if not data:
        return {
            "signal": "NO_DATA",
            "bias": "UNKNOWN",
            "strength": 0,
            "support": 0,
            "resistance": 0,
            "current_price": 0,
            "confidence": 0,
            "trigger": {"bullish": "", "bearish": ""},
            "trade_plan": {},
            "summary": "No data available. Fetch during market hours (09:15–15:30 IST).",
            "timestamp": datetime.now().isoformat(),
        }

    metrics = analyze(data)
    prev_metrics = analyze(prev_data) if prev_data else None
    bias = compute_bias(metrics, prev_metrics)

    spot = data.get("spot", 0) or 0
    support = metrics.get("support_level", 0) or int(spot * 0.99)
    resistance = metrics.get("resistance_level", 0) or int(spot * 1.01)
    atm = metrics.get("atm", spot) or spot

    # ── Layer 3: Trigger Engine ───────────────────────────────────────────
    # Get OI changes near key levels
    prev_strikes = prev_data.get("strikes", {}) if prev_data else {}
    ce_oi_resistance_prev = prev_strikes.get(resistance, {}).get("CE", {}).get("oi", 0)
    pe_oi_support_prev = prev_strikes.get(support, {}).get("PE", {}).get("oi", 0)

    ce_oi_resistance = data["strikes"].get(resistance, {}).get("CE", {}).get("oi", 0)
    pe_oi_support = data["strikes"].get(support, {}).get("PE", {}).get("oi", 0)

    ce_chng_resistance = data["strikes"].get(resistance, {}).get("CE", {}).get("change_oi", 0)
    pe_chng_support = data["strikes"].get(support, {}).get("PE", {}).get("change_oi", 0)

    # Spot distance from levels
    dist_resistance = ((spot - resistance) / resistance) * 100 if resistance else 0
    dist_support = ((support - spot) / support) * 100 if support else 0

    # ── Confidence Score ─────────────────────────────────────────────────
    pcr = metrics.get("pcr_total", 1.0)
    oi_strength = abs(pcr - 1.0) * 2
    oi_strength = min(1.0, oi_strength)

    volume_near = metrics.get("gamma_approx", 0)
    vol_spike = min(1.0, volume_near / 50000)

    bias_strength = bias.get("strength", 0.5)

    net_buildup = metrics.get("pe_buildup", 0) + metrics.get("pe_unwind", 0) - (metrics.get("ce_buildup", 0) + metrics.get("ce_unwind", 0))
    oi_velocity = min(1.0, abs(net_buildup) / 100000)

    iv_skew_abs = abs(metrics.get("iv_skew", 0))
    iv_factor = min(1.0, iv_skew_abs / 5)

    confidence = round(
        oi_strength * 0.30 +
        vol_spike * 0.20 +
        bias_strength * 0.25 +
        oi_velocity * 0.15 +
        iv_factor * 0.10,
        2
    )
    confidence = max(0.1, min(0.95, confidence))

    # ── Signal determination ──────────────────────────────────────────────
    if bias["bias"] == "BEARISH" and spot > resistance and ce_chng_resistance < 0:
        signal = "TRIGGERED BUY"  # Short covering at resistance = bullish reversal
    elif bias["bias"] == "BULLISH" and spot < support and pe_chng_support < 0:
        signal = "TRIGGERED SELL"  # Short covering at support = bearish reversal
    elif bias["bias"] == "BULLISH" and spot > resistance:
        signal = "BREAKOUT LONG"
    elif bias["bias"] == "BEARISH" and spot < support:
        signal = "BREAKDOWN SHORT"
    elif bias["bias"] == "BULLISH":
        signal = "SETUP LONG"
    elif bias["bias"] == "BEARISH":
        signal = "SETUP SHORT"
    else:
        signal = "WAIT"

    # ── Trigger descriptions ──────────────────────────────────────────────
    trigger_bull = f"Above {resistance:,} with CE unwinding (OI -{(abs(ce_chng_resistance)/1000):.0f}K)"
    trigger_bear = f"Below {support:,} with PE unwinding (OI -{(abs(pe_chng_support)/1000):.0f}K)"

    # ── Trade plan ────────────────────────────────────────────────────────
    if signal.startswith("SETUP") or signal.startswith("BREAKOUT"):
        entry = spot
        sl = support
        target = resistance + (resistance - support)
        risk = abs(entry - sl)
        reward = abs(target - entry)
        rr = round(reward / max(risk, 1), 2)
        trade_plan = {
            "direction": "LONG",
            "entry": entry,
            "stop_loss": sl,
            "target": target,
            "risk_reward": rr,
            "strategy": "Bull Call Spread" if entry > atm else "Buy ATM Call",
            "time_frame": "Intraday / expiry",
        }
    elif signal.startswith("BREAKDOWN") or signal.startswith("TRIGGERED SELL"):
        entry = spot
        sl = resistance
        target = support - (resistance - support)
        risk = abs(sl - entry)
        reward = abs(entry - target)
        rr = round(reward / max(risk, 1), 2)
        trade_plan = {
            "direction": "SHORT",
            "entry": entry,
            "stop_loss": sl,
            "target": target,
            "risk_reward": rr,
            "strategy": "Bear Put Spread" if entry > atm else "Buy ATM Put",
            "time_frame": "Intraday / expiry",
        }
    else:
        trade_plan = {
            "direction": None,
            "entry": None,
            "stop_loss": None,
            "target": None,
            "risk__reward": None,
            "strategy": "No position",
            "time_frame": None,
        }

    # ── VIX / Volatility filter ───────────────────────────────────────────
    vix_filter = "PASS"
    if metrics.get("iv_skew", 0) < -5:
        vix_filter = "LOW_VOL — avoid breakout trades"
    elif metrics.get("iv_skew", 0) > 8:
        vix_filter = "HIGH_VOL — use wider stops"

    # ── Time decay awareness ─────────────────────────────────────────────
    expiry = data.get("expiry", "")
    hour = datetime.now().hour
    if expiry:
        day_left = "today" if "NIFTY" in expiry else expiry
    else:
        day_left = "unknown"

    if hour >= 14:
        time_decade = "HIGH — theta decay accelerates, avoid new positions"
    elif hour >= 12:
        time_decade = "MEDIUM — manage existing positions"
    else:
        time_decay = "LOW — full theta benefit"

    # ── Invalidation ────────────────────────────────────────────────────
    if signal.startswith("SETUP LONG") or signal == "BREAKOUT LONG":
        invalidation = f"Break below {support} decisively"
    elif signal.startswith("SETUP SHORT") or signal == "BREAKDOWN SHORT":
        invalidation = f"Break above {resistance} decisively"
    elif signal == "TRIGGERED BUY":
        invalidation = f"Fall back below {support}"
    elif signal == "TRIGGERED SELL":
        invalidation = f"Rise back above {resistance}"
    else:
        invalidation = "Signal flips"

    # ── Summary ──────────────────────────────────────────────────────────
    bias_txt = bias["bias"].lower()
    strength_lbl = "strong" if bias["strength"] > 0.7 else "moderate" if bias["strength"] > 0.4 else "weak"
    signal_txt = signal.replace("_", " ")

    summary = (
        f"{bias_txt.capitalize()} bias ({strength_lbl}) — "
        f"PCR {pcr:.2f}. "
        f"{signal_txt}. "
        f"Support {support:,} | Resistance {resistance:,}. "
        f"Confidence: {confidence:.0%}."
    )

    result = {
        "signal": signal,
        "bias": bias["bias"],
        "strength": bias["strength"],
        "raw_score": bias["raw_score"],
        "support": support,
        "resistance": resistance,
        "atm": atm,
        "max_pain": metrics.get("max_pain", 0),
        "current_price": spot,
        "distance_from_support": round(dist_support, 2),
        "distance_from_resistance": round(dist_resistance, 2),
        "confidence": confidence,
        "trigger": {
            "bullish": trigger_bull,
            "bearish": trigger_bear,
        },
        "trade_plan": trade_plan,
        "summary": summary,
        "invalidation": invalidation,
        "metadata": {
            "pcr_total": pcr,
            "pcr_near_atm": metrics.get("pcr_near_atm", 0),
            "total_ce_oi": metrics.get("total_ce_oi", 0),
            "total_pe_oi": metrics.get("total_pe_oi", 0),
            "ce_buildup": metrics.get("ce_buildup", 0),
            "pe_buildup": metrics.get("pe_buildup", 0),
            "iv_skew": metrics.get("iv_skew", 0),
            "vix_filter": vix_filter,
            "time_decay": time_decade if "time_decade" in dir() else "LOW",
            "near_strike_count": metrics.get("near_strike_count", 0),
        },
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
    }

    return result


def save_signal(symbol: str = "NIFTY", db: str = None) -> dict:
    if db is None:
        db = str(DB)

    sig = get_signal(symbol)

    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, symbol TEXT NOT NULL,
            signal TEXT, bias TEXT, confidence REAL,
            support INTEGER, resistance INTEGER, spot REAL,
            max_pain REAL, signal_json TEXT,
            UNIQUE(symbol, timestamp)
        )
    """)
    conn.execute("""
        INSERT OR REPLACE INTO signals
        (timestamp, symbol, signal, bias, confidence, support, resistance, spot, max_pain, signal_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sig["timestamp"], symbol, sig["signal"], sig["bias"], sig["confidence"],
          sig["support"], sig["resistance"], sig["current_price"],
          sig["max_pain"], json.dumps(sig)))
    conn.commit()
    conn.close()

    return sig


if __name__ == "__main__":
    sig = get_signal("NIFTY")
    print(json.dumps(sig, indent=2, default=str))