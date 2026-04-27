#!/usr/bin/env python3
"""Analyzer - Option chain metrics, bias, levels, OI analysis"""

from typing import Optional


def analyze(data: dict) -> dict:
    spot = data.get("spot", 0) or 0
    strikes = data.get("strikes", {})

    if not strikes:
        return {}

    # ── PCR ──────────────────────────────────────────────────────────────
    total_ce_oi = sum(s.get("CE", {}).get("oi", 0) for s in strikes.values())
    total_pe_oi = sum(s.get("PE", {}).get("oi", 0) for s in strikes.values())
    pcr_total = round(total_pe_oi / max(total_ce_oi, 1), 3)

    # Near-ATM (±1000)
    near = {s: v for s, v in strikes.items() if abs(s - spot) <= 1000}
    near_ce = sum(s.get("CE", {}).get("oi", 0) for s in near.values())
    near_pe = sum(s.get("PE", {}).get("oi", 0) for s in near.values())
    pcr_near = round(near_pe / max(near_ce, 1), 3)

    # ── ATM ──────────────────────────────────────────────────────────────
    atm_strike = min(strikes.keys(), key=lambda s: abs(s - spot)) if strikes else 0

    # ── Max Pain ─────────────────────────────────────────────────────────
    max_pain_strike, min_pain_loss = atm_strike, float("inf")
    for s in strikes:
        ce_loss = sum(max(0, s - k) * v.get("CE", {}).get("oi", 0) for k, v in strikes.items())
        pe_loss = sum(max(0, k - s) * v.get("PE", {}).get("oi", 0) for k, v in strikes.items())
        total = ce_loss + pe_loss
        if total < min_pain_loss:
            min_pain_loss = total
            max_pain_strike = s

    # ── Key levels ───────────────────────────────────────────────────────
    top_ce = sorted(strikes.items(), key=lambda x: x[1].get("CE", {}).get("oi", 0), reverse=True)[:5]
    top_pe = sorted(strikes.items(), key=lambda x: x[1].get("PE", {}).get("oi", 0), reverse=True)[:5]

    resistance = [{"strike": int(s), "oi": v["CE"]["oi"], "chng_oi": v["CE"].get("change_oi", 0)}
                  for s, v in top_ce if v.get("CE", {}).get("oi")]
    support = [{"strike": int(s), "oi": v["PE"]["oi"], "chng_oi": v["PE"].get("change_oi", 0)}
               for s, v in top_pe if v.get("PE", {}).get("oi")]

    resistance_level = resistance[0]["strike"] if resistance else int(spot * 1.01)
    support_level = support[0]["strike"] if support else int(spot * 0.99)

    # ── OI Buildup / Unwinding ────────────────────────────────────────────
    ce_buildup = sum(max(0, s.get("CE", {}).get("change_oi", 0)) for s in strikes.values())
    ce_unwind = abs(sum(min(0, s.get("CE", {}).get("change_oi", 0)) for s in strikes.values()))
    pe_buildup = sum(max(0, s.get("PE", {}).get("change_oi", 0)) for s in strikes.values())
    pe_unwind = abs(sum(min(0, s.get("PE", {}).get("change_oi", 0)) for s in strikes.values()))

    # ── IV Analysis ──────────────────────────────────────────────────────
    otm_ce = [(s, v) for s, v in strikes.items() if s > atm_strike and v.get("CE", {}).get("iv")]
    otm_pe = [(s, v) for s, v in strikes.items() if s < atm_strike and v.get("PE", {}).get("iv")]

    avg_ce_iv = sum(v["CE"]["iv"] for _, v in otm_ce) / max(len(otm_ce), 1)
    avg_pe_iv = sum(v["PE"]["iv"] for _, v in otm_pe) / max(len(otm_pe), 1)
    iv_skew = round(avg_pe_iv - avg_ce_iv, 2)

    # ── Gamma Exposure estimate ──────────────────────────────────────────
    gamma_approx = sum(v.get("CE", {}).get("oi", 0) + v.get("PE", {}).get("oi", 0)
                      for v in near.values()) / max(len(near), 1)

    return {
        "spot": spot,
        "atm": atm_strike,
        "max_pain": max_pain_strike,
        "pcr_total": pcr_total,
        "pcr_near_atm": pcr_near,
        "total_ce_oi": int(total_ce_oi),
        "total_pe_oi": int(total_pe_oi),
        "resistance": resistance,
        "support": support,
        "resistance_level": resistance_level,
        "support_level": support_level,
        "ce_buildup": int(ce_buildup),
        "ce_unwind": int(ce_unwind),
        "pe_buildup": int(pe_buildup),
        "pe_unwind": int(pe_unwind),
        "iv_skew": iv_skew,
        "avg_ce_iv": round(avg_ce_iv, 2),
        "avg_pe_iv": round(avg_pe_iv, 2),
        "gamma_approx": int(gamma_approx),
        "near_strike_count": len(near),
    }


def compute_bias(metrics: dict, prev: Optional[dict] = None) -> dict:
    pcr = metrics.get("pcr_total", 1.0)
    ce_oi = metrics.get("total_ce_oi", 1)
    pe_oi = metrics.get("total_pe_oi", 1)
    ce_buildup = metrics.get("ce_buildup", 0)
    pe_buildup = metrics.get("pe_buildup", 0)
    ce_unwind = metrics.get("ce_unwind", 0)
    pe_unwind = metrics.get("pe_unwind", 0)
    iv_skew = metrics.get("iv_skew", 0)
    spot = metrics.get("spot", 0) or 0
    atm = metrics.get("atm", spot) or spot

    # Layer 1: PCR + OI change momentum
    raw = 0.5
    if pcr > 1.3: raw += 0.2
    elif pcr > 1.5: raw += 0.3
    elif pcr < 0.8: raw -= 0.2
    elif pcr < 0.6: raw -= 0.3

    # OI shift momentum
    net_oi_shift = (pe_buildup - pe_unwind) - (ce_buildup - ce_unwind)
    if net_oi_shift > 50000: raw += 0.15
    elif net_oi_shift < -50000: raw -= 0.15

    # IV skew contribution
    if iv_skew > 3: raw += 0.1
    elif iv_skew < -3: raw -= 0.1

    # Previous signal momentum
    if prev:
        prev_pcr = prev.get("pcr_total", 1.0)
        if pcr > prev_pcr + 0.1: raw += 0.05
        elif pcr < prev_pcr - 0.1: raw -= 0.05

    raw = max(0.0, min(1.0, raw))

    if raw >= 0.65:
        bias = "BULLISH"
        strength = round(min(1.0, (raw - 0.65) / 0.35), 2)
    elif raw <= 0.35:
        bias = "BEARISH"
        strength = round(min(1.0, (0.35 - raw) / 0.35), 2)
    else:
        bias = "NEUTRAL"
        strength = round(1 - abs(raw - 0.5) / 0.5, 2)

    return {"bias": bias, "strength": strength, "raw_score": round(raw, 3)}