"""
NSE Option Chain Signal Engine
Uses Gemini 2.0 Flash for AI-powered signal generation
Usage: python nse_signal.py --file option-chain.csv --key YOUR_GEMINI_KEY
"""

import csv
import sys
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime


# ── Parse Option Chain CSV ────────────────────────────────────────────────────

def clean(val):
    if not val or val.strip() in ['-', '', ' ']:
        return None
    try:
        return float(val.strip().replace(',', ''))
    except:
        return None


def parse_option_chain(filepath):
    rows = []
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        lines = list(reader)

    # NSE format: row 0 = CALLS/PUTS label, row 1 = column headers, row 2+ = data
    for line in lines[2:]:
        if len(line) < 22:
            continue
        strike = clean(line[11])
        if not strike or strike <= 0:
            continue
        rows.append({
            'strike':       strike,
            'ce_oi':        clean(line[1])  or 0,
            'ce_chng_oi':   clean(line[2])  or 0,
            'ce_vol':       clean(line[3])  or 0,
            'ce_iv':        clean(line[4]),
            'ce_ltp':       clean(line[5]),
            'ce_chng':      clean(line[6]),
            'pe_oi':        clean(line[21]) or 0,
            'pe_chng_oi':   clean(line[20]) or 0,
            'pe_vol':       clean(line[19]) or 0,
            'pe_iv':        clean(line[18]),
            'pe_ltp':       clean(line[17]),
            'pe_chng':      clean(line[16]),
        })

    return sorted(rows, key=lambda x: x['strike'])


# ── Compute Signal Metrics ────────────────────────────────────────────────────

def compute_metrics(rows):
    total_ce_oi = sum(r['ce_oi'] for r in rows)
    total_pe_oi = sum(r['pe_oi'] for r in rows)
    pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 0

    # ATM: strike where CE LTP ≈ PE LTP
    valid = [r for r in rows if r['ce_ltp'] and r['pe_ltp']]
    atm_row = min(valid, key=lambda r: abs(r['ce_ltp'] - r['pe_ltp'])) if valid else rows[len(rows)//2]
    atm = atm_row['strike']

    # Max Pain
    strikes = [r['strike'] for r in rows]
    min_pain, max_pain_strike = float('inf'), atm
    for s in strikes:
        ce_loss = sum(max(0, s - r['strike']) * r['ce_oi'] for r in rows)
        pe_loss = sum(max(0, r['strike'] - s) * r['pe_oi'] for r in rows)
        total = ce_loss + pe_loss
        if total < min_pain:
            min_pain = total
            max_pain_strike = s

    # Near-ATM PCR (±1000)
    near = [r for r in rows if abs(r['strike'] - atm) <= 1000]
    near_ce = sum(r['ce_oi'] for r in near)
    near_pe = sum(r['pe_oi'] for r in near)
    near_pcr = round(near_pe / near_ce, 3) if near_ce > 0 else 0

    # Top OI strikes
    top_ce_oi = sorted(rows, key=lambda r: r['ce_oi'], reverse=True)[:8]
    top_pe_oi = sorted(rows, key=lambda r: r['pe_oi'], reverse=True)[:8]

    # OI buildup and unwinding
    ce_buildup  = sorted([r for r in rows if r['ce_chng_oi'] > 0], key=lambda r: r['ce_chng_oi'], reverse=True)[:5]
    pe_buildup  = sorted([r for r in rows if r['pe_chng_oi'] > 0], key=lambda r: r['pe_chng_oi'], reverse=True)[:5]
    ce_unwind   = sorted([r for r in rows if r['ce_chng_oi'] < 0], key=lambda r: r['ce_chng_oi'])[:5]
    pe_unwind   = sorted([r for r in rows if r['pe_chng_oi'] < 0], key=lambda r: r['pe_chng_oi'])[:5]

    # IV skew: compare OTM CE vs OTM PE IV near ATM
    otm_ce = [r for r in rows if r['strike'] > atm and r['ce_iv'] and abs(r['strike'] - atm) < 500]
    otm_pe = [r for r in rows if r['strike'] < atm and r['pe_iv'] and abs(r['strike'] - atm) < 500]
    avg_otm_ce_iv = round(sum(r['ce_iv'] for r in otm_ce) / len(otm_ce), 2) if otm_ce else None
    avg_otm_pe_iv = round(sum(r['pe_iv'] for r in otm_pe) / len(otm_pe), 2) if otm_pe else None

    return {
        'atm': atm,
        'max_pain': max_pain_strike,
        'pcr_total': pcr,
        'pcr_near_atm': near_pcr,
        'total_ce_oi': int(total_ce_oi),
        'total_pe_oi': int(total_pe_oi),
        'avg_otm_ce_iv': avg_otm_ce_iv,
        'avg_otm_pe_iv': avg_otm_pe_iv,
        'top_ce_oi': [{'strike': r['strike'], 'oi': int(r['ce_oi']), 'chng_oi': int(r['ce_chng_oi']), 'iv': r['ce_iv'], 'ltp': r['ce_ltp']} for r in top_ce_oi],
        'top_pe_oi': [{'strike': r['strike'], 'oi': int(r['pe_oi']), 'chng_oi': int(r['pe_chng_oi']), 'iv': r['pe_iv'], 'ltp': r['pe_ltp']} for r in top_pe_oi],
        'ce_buildup': [{'strike': r['strike'], 'chng_oi': int(r['ce_chng_oi']), 'oi': int(r['ce_oi'])} for r in ce_buildup],
        'pe_buildup': [{'strike': r['strike'], 'chng_oi': int(r['pe_chng_oi']), 'oi': int(r['pe_oi'])} for r in pe_buildup],
        'ce_unwind':  [{'strike': r['strike'], 'chng_oi': int(r['ce_chng_oi']), 'oi': int(r['ce_oi'])} for r in ce_unwind],
        'pe_unwind':  [{'strike': r['strike'], 'chng_oi': int(r['pe_chng_oi']), 'oi': int(r['pe_oi'])} for r in pe_unwind],
    }


# ── Build Gemini Prompt ───────────────────────────────────────────────────────

def build_prompt(metrics, expiry, symbol='NIFTY'):
    def fmt_oi_list(items, side):
        lines = []
        for x in items:
            iv_str = f"IV:{x['iv']:.1f}" if x['iv'] else ''
            ltp_str = f"LTP:{x['ltp']}" if x.get('ltp') else ''
            lines.append(f"  {side} {x['strike']:.0f} | OI:{x['oi']:,} | ΔOI:{x['chng_oi']:+,} {iv_str} {ltp_str}")
        return '\n'.join(lines)

    def fmt_chng_list(items, side):
        return '\n'.join([f"  {side} {x['strike']:.0f} | ΔOI:{x['chng_oi']:+,} | Total:{x['oi']:,}" for x in items])

    pcr_signal = 'BULLISH' if metrics['pcr_total'] > 1.2 else ('BEARISH' if metrics['pcr_total'] < 0.8 else 'NEUTRAL')
    iv_skew = ''
    if metrics['avg_otm_ce_iv'] and metrics['avg_otm_pe_iv']:
        diff = metrics['avg_otm_pe_iv'] - metrics['avg_otm_ce_iv']
        iv_skew = f"OTM PE IV avg: {metrics['avg_otm_pe_iv']} | OTM CE IV avg: {metrics['avg_otm_ce_iv']} | Skew: {diff:+.2f} ({'PE skew = fear/put demand' if diff > 1 else 'CE skew = call demand' if diff < -1 else 'balanced'})"

    return f"""You are an expert NSE F&O options analyst. Analyze the following NIFTY option chain data for expiry {expiry} and generate a precise trade signal.

=== OPTION CHAIN SNAPSHOT ===
Symbol: {symbol} | Expiry: {expiry} | Analyzed at: {datetime.now().strftime('%H:%M on %d-%b-%Y')}

ATM Strike: {metrics['atm']:.0f}
Max Pain: {metrics['max_pain']:.0f} (spot likely to gravitate here by expiry)

PCR (Total OI): {metrics['pcr_total']} → {pcr_signal}
PCR (Near ATM ±1000): {metrics['pcr_near_atm']}
Total CE OI: {metrics['total_ce_oi']:,}
Total PE OI: {metrics['total_pe_oi']:,}

IV Skew: {iv_skew or 'Insufficient data'}

TOP CE OI STRIKES (Key Resistance):
{fmt_oi_list(metrics['top_ce_oi'], 'CE')}

TOP PE OI STRIKES (Key Support):
{fmt_oi_list(metrics['top_pe_oi'], 'PE')}

FRESH OI BUILDUP:
CE Buildup (call writers adding = resistance hardening):
{fmt_chng_list(metrics['ce_buildup'], 'CE') or '  None significant'}

PE Buildup (put writers adding = support building):
{fmt_chng_list(metrics['pe_buildup'], 'PE') or '  None significant'}

OI UNWINDING:
CE Unwinding (call writers covering = resistance softening):
{fmt_chng_list(metrics['ce_unwind'], 'CE') or '  None significant'}

PE Unwinding (put buyers exiting = support weakening):
{fmt_chng_list(metrics['pe_unwind'], 'PE') or '  None significant'}

=== YOUR TASK ===
Respond ONLY with a valid JSON object in this exact format:

{{
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL" | "SIDEWAYS",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "spot_range_today": {{"low": <number>, "high": <number>}},
  "key_resistance": [<strike1>, <strike2>],
  "key_support": [<strike1>, <strike2>],
  "max_pain_bias": "<explain where spot is vs max pain and what it implies>",
  "pcr_interpretation": "<interpret PCR and OI changes together>",
  "oi_story": "<2-3 sentences: what smart money is doing based on OI buildup/unwinding>",
  "suggested_strategy": "<specific options strategy with strikes, e.g. Bear Call Spread 24000-24200CE>",
  "invalidation": "<what price action would invalidate this signal>",
  "summary": "<1 line plain English signal for a trader>"
}}"""


# ── Call Gemini API ───────────────────────────────────────────────────────────

def call_gemini(prompt, api_key, model='gemini-2.0-flash'):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 1024}
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result['candidates'][0]['content']['parts'][0]['text']
    except urllib.error.HTTPError as e:
        return f"API Error {e.code}: {e.read().decode()}"
    except Exception as e:
        return f"Error: {e}"


# ── Pretty Print Signal ───────────────────────────────────────────────────────

def print_signal(raw_response, metrics, expiry):
    print("\n" + "="*60)
    print(f"  NIFTY SIGNAL | Expiry: {expiry}")
    print("="*60)

    # Try to parse JSON from response
    text = raw_response.strip()
    if '```' in text:
        text = text.split('```')[1]
        if text.startswith('json'):
            text = text[4:]
    try:
        sig = json.loads(text.strip())
        emoji = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '🟡', 'SIDEWAYS': '🟠'}.get(sig.get('signal',''), '⚪')
        conf_emoji = {'HIGH': '🔥', 'MEDIUM': '✅', 'LOW': '⚠️'}.get(sig.get('confidence',''), '')

        print(f"\n  {emoji} SIGNAL    : {sig.get('signal','?')}  {conf_emoji} {sig.get('confidence','?')} CONFIDENCE")
        print(f"  📍 ATM       : {metrics['atm']:.0f}  |  Max Pain: {metrics['max_pain']:.0f}")
        print(f"  📊 PCR       : {metrics['pcr_total']} (Near-ATM: {metrics['pcr_near_atm']})")
        r = sig.get('spot_range_today', {})
        print(f"  📈 Range     : {r.get('low','?')} – {r.get('high','?')}")
        print(f"  🛡️  Support   : {sig.get('key_support', [])}")
        print(f"  🚧 Resistance: {sig.get('key_resistance', [])}")
        print(f"\n  📌 Strategy  : {sig.get('suggested_strategy','?')}")
        print(f"  ❌ Invalidate: {sig.get('invalidation','?')}")
        print(f"\n  OI Story: {sig.get('oi_story','?')}")
        print(f"  PCR Read: {sig.get('pcr_interpretation','?')}")
        print(f"  Max Pain: {sig.get('max_pain_bias','?')}")
        print(f"\n  ── SUMMARY ─────────────────────────────────────")
        print(f"  {sig.get('summary','?')}")
    except json.JSONDecodeError:
        print("\n  Raw Gemini Response:")
        print(raw_response)

    print("="*60 + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='NSE Option Chain → Gemini Signal')
    parser.add_argument('--file', required=True, help='Path to NSE option chain CSV')
    parser.add_argument('--key', required=True, help='Gemini API key')
    parser.add_argument('--expiry', default='28-Apr-2026', help='Expiry date label')
    parser.add_argument('--symbol', default='NIFTY', help='Underlying symbol')
    parser.add_argument('--model', default='gemini-2.0-flash', help='Gemini model')
    parser.add_argument('--dump-prompt', action='store_true', help='Print prompt without calling API')
    args = parser.parse_args()

    print(f"\n📂 Parsing: {args.file}")
    rows = parse_option_chain(args.file)
    print(f"✅ {len(rows)} strikes loaded")

    print("⚙️  Computing metrics...")
    metrics = compute_metrics(rows)
    print(f"   ATM: {metrics['atm']:.0f} | Max Pain: {metrics['max_pain']:.0f} | PCR: {metrics['pcr_total']}")

    prompt = build_prompt(metrics, args.expiry, args.symbol)

    if args.dump_prompt:
        print("\n─── PROMPT ───")
        print(prompt)
        return

    print(f"🤖 Calling Gemini ({args.model})...")
    response = call_gemini(prompt, args.key, args.model)
    print_signal(response, metrics, args.expiry)


if __name__ == '__main__':
    main()