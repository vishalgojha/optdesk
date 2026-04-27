#!/usr/bin/env python3
"""NSE Option Chain Web UI"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import sqlite3
import json
import os
import time
from datetime import datetime, time as dtime
from pathlib import Path
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import urllib.error
from datetime import datetime, time as dtime, timedelta
import pytz

IST = pytz.timezone('Asia/Kolkata')

app = FastAPI(title="NSE Option Chain Signal", version="1.0")

def get_market_info():
    """Get market open/close times and next open in IST"""
    now_ist = datetime.now(IST)
    now_time = now_ist.time()

    market_open = dtime(9, 15)
    market_close = dtime(15, 30)

    is_open = market_open <= now_time <= market_close

    # Day of week (0=Mon, 6=Sun)
    dow = now_ist.weekday()
    is_weekend = dow >= 5

    # Next open
    if is_open:
        next_open = None
        closes_at = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        time_left = closes_at - now_ist
        time_left_secs = int(time_left.total_seconds())
    elif is_weekend:
        next_open = "Monday 09:15 IST"
        time_left_secs = None
    else:
        if now_time < market_open:
            next_open_dt = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        else:
            next_open_dt = now_ist.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(days=1)
            if next_open_dt.weekday() >= 5:
                next_open_dt += timedelta(days=(7 - next_open_dt.weekday()))
        next_open = next_open_dt.strftime("%A %d %b, %H:%M IST")
        time_left_secs = int((next_open_dt - now_ist).total_seconds())

    return {
        "is_open": is_open,
        "is_weekend": is_weekend,
        "current_time_ist": now_ist.strftime("%H:%M:%S"),
        "current_date_ist": now_ist.strftime("%d %b %Y (%A)"),
        "market_open_time": "09:15 IST",
        "market_close_time": "15:30 IST",
        "next_open": next_open,
        "time_left_secs": time_left_secs,
    }


def get_sgx_nifty():
    """Fetch SGX Nifty / NSE Nifty price via yfinance"""
    try:
        import yfinance as yf
        # Try ^NSEI (NSE Nifty 50) as primary - available during extended hours
        tk = yf.Ticker("^NSEI")
        h = tk.history(period="1d", timeout=5)
        if not h.empty:
            return round(h["Close"].iloc[-1], 2)
    except:
        pass
    return None


def clean(val):
    if not val or val.strip() in ['-', '', ' ']:
        return None
    try:
        return float(val.strip().replace(',', ''))
    except:
        return None


def parse_csv(csv_path):
    import csv as csvmod
    rows = []
    with open(csv_path, 'r') as f:
        reader = csvmod.reader(f)
        lines = list(reader)
    for line in lines[2:]:
        if len(line) < 17:
            continue
        strike = clean(line[8])
        if not strike or strike <= 0:
            continue
        rows.append({
            'strike': strike,
            'ce_oi': clean(line[0]) or 0,
            'ce_chng_oi': clean(line[1]) or 0,
            'ce_vol': clean(line[2]) or 0,
            'ce_iv': clean(line[3]),
            'ce_ltp': clean(line[4]),
            'ce_chng': clean(line[5]),
            'pe_oi': clean(line[9]) or 0,
            'pe_chng_oi': clean(line[10]) or 0,
            'pe_vol': clean(line[11]) or 0,
            'pe_iv': clean(line[12]),
            'pe_ltp': clean(line[13]),
            'pe_chng': clean(line[14]),
        })
    return sorted(rows, key=lambda x: x['strike'])


def compute_metrics(rows):
    total_ce = sum(r['ce_oi'] for r in rows)
    total_pe = sum(r['pe_oi'] for r in rows)
    pcr = round(total_pe / total_ce, 3) if total_ce > 0 else 0
    valid = [r for r in rows if r['ce_ltp'] and r['pe_ltp']]
    atm_row = min(valid, key=lambda r: abs(r['ce_ltp'] - r['pe_ltp'])) if valid else rows[len(rows)//2]
    atm = atm_row['strike']

    strikes = [r['strike'] for r in rows]
    min_pain, max_pain_strike = float('inf'), atm
    for s in strikes:
        ce_loss = sum(max(0, s - r['strike']) * r['ce_oi'] for r in rows)
        pe_loss = sum(max(0, r['strike'] - s) * r['pe_oi'] for r in rows)
        total = ce_loss + pe_loss
        if total < min_pain:
            min_pain = total
            max_pain_strike = s

    near = [r for r in rows if abs(r['strike'] - atm) <= 1000]
    near_ce = sum(r['ce_oi'] for r in near)
    near_pe = sum(r['pe_oi'] for r in near)
    near_pcr = round(near_pe / near_ce, 3) if near_ce > 0 else 0

    top_ce = sorted(rows, key=lambda r: r['ce_oi'], reverse=True)[:8]
    top_pe = sorted(rows, key=lambda r: r['pe_oi'], reverse=True)[:8]

    def fmt_list(items, side):
        return '\n'.join([f"  {side} {r['strike']:.0f} | OI:{r['ce_oi' if side=='CE' else 'pe_oi']:,} | ΔOI:{r['ce_chng_oi' if side=='CE' else 'pe_chng_oi']:+,}" for r in items])

    return {
        'atm': atm,
        'max_pain': max_pain_strike,
        'pcr_total': pcr,
        'pcr_near_atm': near_pcr,
        'total_ce_oi': int(total_ce),
        'total_pe_oi': int(total_pe),
        'top_ce_oi': [{'strike': r['strike'], 'oi': int(r['ce_oi']), 'chng_oi': int(r['ce_chng_oi']), 'iv': r['ce_iv'], 'ltp': r['ce_ltp']} for r in top_ce],
        'top_pe_oi': [{'strike': r['strike'], 'oi': int(r['pe_oi']), 'chng_oi': int(r['pe_chng_oi']), 'iv': r['pe_iv'], 'ltp': r['pe_ltp']} for r in top_pe],
        'fmt_top_ce': fmt_list(top_ce, 'CE'),
        'fmt_top_pe': fmt_list(top_pe, 'PE'),
    }


def generate_signal(metrics, expiry="latest"):
    pcr_signal = 'BULLISH' if metrics['pcr_total'] > 1.2 else ('BEARISH' if metrics['pcr_total'] < 0.8 else 'NEUTRAL')

    top_ce = sorted(metrics['top_ce_oi'], key=lambda x: x['oi'], reverse=True)[:3]
    top_pe = sorted(metrics['top_pe_oi'], key=lambda x: x['oi'], reverse=True)[:3]

    resistance = [int(r['strike']) for r in top_ce]
    support = [int(s['strike']) for s in top_pe]

    atm = metrics['atm']
    max_pain = metrics['max_pain']
    spot_range = max_pain
    range_low = int(spot_range * 0.98)
    range_high = int(spot_range * 1.02)

    if metrics['pcr_total'] > 1.3:
        signal_text = "BULLISH - High put buying indicates strong support"
        strategy = f"Buy PE at support {support[0]} or Bull Put Spread"
        conf = "HIGH" if metrics['pcr_total'] > 1.5 else "MEDIUM"
    elif metrics['pcr_total'] < 0.7:
        signal_text = "BEARISH - High call buying indicates resistance"
        strategy = f"Sell CE at resistance {resistance[0]} or Bear Call Spread"
        conf = "HIGH" if metrics['pcr_total'] < 0.5 else "MEDIUM"
    else:
        signal_text = "NEUTRAL - Balanced OI suggests range-bound movement"
        strategy = f"Iron Condor around ATM {int(atm)} ({int(atm-200)} PUT / {int(atm+200)} CALL)"
        conf = "MEDIUM"

    return {
        "signal": signal_text.split(' - ')[0],
        "confidence": conf,
        "spot_range_today": {"low": range_low, "high": range_high},
        "key_resistance": resistance,
        "key_support": support,
        "max_pain_bias": f"ATM {int(atm)} vs Max Pain {int(max_pain)}. Spot should gravitate toward max pain {int(max_pain)} by expiry.",
        "pcr_interpretation": f"PCR {metrics['pcr_total']} → {pcr_signal}. Total OI: CE {metrics['total_ce_oi']:,} | PE {metrics['total_pe_oi']:,}.",
        "oi_story": f"Highest CE OI at {resistance[0]} (resistance). Highest PE OI at {support[0]} (support). PCR suggests {'bullish' if metrics['pcr_total']>1 else 'bearish' if metrics['pcr_total']<1 else 'neutral'} bias.",
        "suggested_strategy": strategy,
        "invalidation": f"Break above {range_high} or below {range_low} decisively",
        "summary": f"{signal_text}",
        "atm": int(atm),
        "max_pain": int(max_pain),
        "pcr_total": metrics['pcr_total'],
        "pcr_near_atm": metrics['pcr_near_atm'],
        "total_ce_oi": metrics['total_ce_oi'],
        "total_pe_oi": metrics['total_pe_oi'],
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = Path(__file__).parent / "optionchain.db"
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")

BACKEND_URL = os.environ.get("NEXT_PUBLIC_BACKEND_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("API_KEY", "")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "60"))
RATE_WINDOW = 60

_rate_counts = defaultdict(list)
_poll_counts = defaultdict(list)


def rate_limit(client: str, limit: int = RATE_LIMIT, window: int = RATE_WINDOW) -> bool:
    now = time.time()
    _rate_counts[client] = [t for t in _rate_counts[client] if now - t < window]
    _rate_counts[client].append(now)
    return len(_rate_counts[client]) <= limit


def check_api_key(request: Request) -> None:
    if not API_KEY:
        return
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

STATICS = Path(__file__).parent / "static"
STATICS.mkdir(exist_ok=True)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Option Chain Signals</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0a0a1a;color:#e0e0f0;min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:20px}
header{display:flex;justify-content:space-between;align-items:center;padding:20px 0;border-bottom:1px solid #2a2a4a;margin-bottom:30px;flex-wrap:wrap;gap:10px}
header h1{font-size:1.5rem;color:#00d4ff;text-shadow:0 0 20px #00d4ff40}
header .status{display:flex;flex-direction:column;align-items:flex-end;gap:4px;font-size:.9rem}
.dot{width:10px;height:10px;border-radius:50%;background:#ff4444;box-shadow:0 0 10px #ff4444}
.dot.live{background:#44ff88;box-shadow:0 0 10px #44ff88;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.live-tag{color:#44ff88;font-weight:600}
.closed-tag{color:#888}
.countdown{color:#00d4ff;font-weight:600}
.sgx-bar{background:#0f0f2a;border:1px solid #1a1a3a;border-radius:8px;padding:8px 16px;font-size:.85rem;color:#a0a0c0;margin-top:5px}
.sgx-bar strong{color:#00d4ff}
.ticker-wrap{display:flex;gap:15px;font-size:.85rem;align-items:center}
.symbols{display:flex;gap:10px;margin-bottom:20px}
.sym-btn{padding:8px 20px;background:#1a1a3a;border:1px solid #3a3a6a;border-radius:8px;color:#a0a0c0;cursor:pointer;transition:all .2s}
.sym-btn:hover,.sym-btn.active{background:#2a2a5a;border-color:#00d4ff;color:#00d4ff;box-shadow:0 0 15px #00d4ff30}
.signal-card{background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:25px;margin-bottom:20px}
.signal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
.signal-badge{font-size:1.3rem;font-weight:700;padding:6px 16px;border-radius:8px}
.signal-badge.BULLISH{background:#003300;color:#44ff88}
.signal-badge.BEARISH{background:#330000;color:#ff4444}
.signal-badge.NEUTRAL{background:#333300;color:#ffff44}
.signal-badge.SIDEWAYS{background:#332200;color:#ffaa44}
.confidence{font-size:.85rem;padding:4px 12px;background:#1a1a3a;border-radius:20px;color:#a0a0c0}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.metric{background:#0a0a1a;border:1px solid #1a1a3a;border-radius:8px;padding:12px;text-align:center}
.metric .label{font-size:.7rem;color:#666;text-transform:uppercase;letter-spacing:1px}
.metric .val{font-size:1.2rem;font-weight:600;margin-top:4px}
.metric .val.green{color:#44ff88}
.metric .val.red{color:#ff4444}
.metric .val.cyan{color:#00d4ff}
.strategy{background:#0f0f2a;border:1px solid #00d4ff30;border-radius:8px;padding:15px;margin-bottom:15px}
.strategy h3{color:#00d4ff;font-size:.9rem;margin-bottom:8px}
.strategy-text{font-size:1.1rem;font-weight:500;color:#fff}
.notes{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-bottom:15px}
.note{background:#0a0a1a;border-radius:8px;padding:15px}
.note h4{font-size:.8rem;color:#888;margin-bottom:6px;text-transform:uppercase}
.note p{font-size:.9rem;line-height:1.5;color:#b0b0d0}
.invalidate{background:#1a0a0a;border:1px solid #ff444440;border-left:3px solid #ff4444;border-radius:8px;padding:12px;font-size:.9rem;color:#ff8888;margin-bottom:15px}
.summary{background:#0a0a1a;border-radius:8px;padding:15px;text-align:center}
.summary p{font-size:1.3rem;font-weight:600;color:#fff}
.refresh{display:flex;justify-content:center;gap:15px;margin-top:20px}
.btn{padding:10px 25px;border-radius:8px;border:none;font-size:.9rem;cursor:pointer;transition:all .2s;font-weight:500}
.btn-primary{background:#00d4ff;color:#000}
.btn-primary:hover{box-shadow:0 0 20px #00d4ff60}
.btn-secondary{background:#2a2a4a;color:#a0a0c0}
.btn-secondary:hover{background:#3a3a5a}
.last-update{text-align:center;color:#555;font-size:.8rem;margin-top:10px}
.historical{background:#12122a;border:1px solid #2a2a4a;border-radius:12px;padding:20px;margin-top:20px}
.historical h3{color:#888;font-size:.9rem;margin-bottom:15px}
.historical-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:8px}
.hist-row{display:flex;flex-direction:column;align-items:center;background:#0a0a1a;border-radius:6px;padding:8px;font-size:.75rem}
.hist-row .ts{color:#555;font-size:.65rem}
.hist-row .val{font-weight:600;margin-top:3px}
.hist-row.bullish .val{color:#44ff88}
.hist-row.bearish .val{color:#ff4444}
.hist-row.neutral .val{color:#ffff44}
.empty{text-align:center;padding:60px;color:#555;font-size:1rem}
.loading{text-align:center;padding:40px;color:#00d4ff}
.spinner{border:3px solid #1a1a3a;border-top-color:#00d4ff;border-radius:50%;width:30px;height:30px;animation:spin 1s linear infinite;margin:0 auto 15px}
@keyframes spin{to{transform:rotate(360deg)}}
/* Chat Panel */
.chat-fab{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;background:#00d4ff;border:none;cursor:pointer;font-size:1.5rem;box-shadow:0 4px 20px #00d4ff60;transition:all .3s;z-index:999}
.chat-fab:hover{transform:scale(1.1)}
.chat-panel{position:fixed;bottom:90px;right:24px;width:380px;max-width:calc(100vw-40px);height:520px;background:#12122a;border:1px solid #2a2a4a;border-radius:16px;display:none;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px #00000080;z-index:998;animation:slideUp .3s ease}
.chat-panel.open{display:flex}
@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.chat-header{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;background:#1a1a3a;border-bottom:1px solid #2a2a4a;font-weight:600;color:#00d4ff}
.chat-toggle{background:none;border:none;color:#666;cursor:pointer;font-size:1.2rem;padding:0}
.chat-toggle:hover{color:#fff}
.chat-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;scroll-behavior:smooth}
.chat-msg{max-width:85%;padding:10px 14px;border-radius:12px;font-size:.9rem;line-height:1.4;word-break:break-word}
.chat-msg.user{align-self:flex-end;background:#00d4ff20;border:1px solid #00d4ff40;color:#00d4ff}
.chat-msg.bot{align-self:flex-start;background:#1a1a3a;border:1px solid #2a2a4a;color:#c0c0e0}
.chat-msg.error{background:#2a0a0a;border:1px solid #ff444440;color:#ff6666}
.chat-msg.loading{color:#555;font-style:italic}
.chat-input-wrap{display:flex;gap:8px;padding:12px;border-top:1px solid #2a2a4a;background:#0a0a1a}
.chat-input-wrap input{flex:1;background:#1a1a3a;border:1px solid #2a2a4a;border-radius:8px;padding:10px 12px;color:#e0e0f0;font-size:.9rem;outline:none}
.chat-input-wrap input:focus{border-color:#00d4ff}
.chat-send{background:#00d4ff;border:none;border-radius:8px;padding:10px 16px;cursor:pointer;font-size:1rem;transition:all .2s}
.chat-send:hover{box-shadow:0 0 15px #00d4ff60}
</style>
</head>
<body>
<div class="container">
<header>
<h1>📊 NSE Option Chain Signals</h1>
<div class="status">
<span class="dot" id="dot"></span>
<span id="marketStatus">Checking...</span>
<span class="sgx-bar" id="sgxVal">SGX Nifty: <span style="color:#555">loading...</span></span>
<span id="clock" style="color:#555;font-size:.75rem"></span>
</div>
</header>
<div class="symbols">
<button class="sym-btn active" data-sym="NIFTY">NIFTY</button>
<button class="sym-btn" data-sym="BANKNIFTY">BANKNIFTY</button>
<button class="sym-btn" data-sym="FINNIFTY">FINNIFTY</button>
</div>
<div id="signalArea">
<div class="loading"><div class="spinner"></div>Loading signals...</div>
</div>
<div class="refresh">
<button class="btn btn-primary" onclick="fetchSignal()">🔄 Refresh Signal</button>
<button class="btn btn-secondary" onclick="runPoll()">📡 Fetch Latest Data</button>
</div>
<div class="last-update" id="lastUpdate"></div>
<div class="historical" id="historyArea">
<h3>📜 Signal History</h3>
<div class="hist-grid" id="histGrid"></div>
</div>
</div>
<div class="chat-panel" id="chatPanel">
<div class="chat-header">
<span>AI Analyst</span>
<button class="chat-toggle" onclick="toggleChat()">−</button>
</div>
<div class="chat-messages" id="chatMessages">
<div class="chat-msg bot">Hi! Ask me anything about NSE options, the current signal, or trading strategies.</div>
</div>
<div class="chat-input-wrap">
<input type="text" id="chatInput" placeholder="Ask about options, signals, strategies..." onkeydown="if(event.key==='Enter')sendChat()">
<button class="chat-send" onclick="sendChat()">➤</button>
</div>
</div>
<div class="chat-fab" id="chatFab" onclick="toggleChat()" title="Chat with AI">💬</div>
</div>
</body>
<script>
let currentSym = 'NIFTY';
let lastSignal = null;
let marketInfo = null;
let timerInterval = null;
const BACKEND_URL = /* BACKEND_URL */'http://127.0.0.1:8000'/* */;

function setStatus(info) {
  marketInfo = info;
  const dot = document.getElementById('dot');
  const txt = document.getElementById('marketStatus');
  const sgx = document.getElementById('sgxVal');

  if (info.is_open) {
    dot.classList.add('live');
    txt.innerHTML = `<span class="live-tag">🔴 LIVE</span> Market Open · Closes at ${info.market_close_time} · <span class="countdown" id="countdown"></span>`;
    startCountdown(info.time_left_secs);
  } else {
    dot.classList.remove('live');
    if (info.is_weekend) {
      txt.innerHTML = `<span class="closed-tag">⏰ Weekend</span> Market opens ${info.next_open}`;
    } else {
      txt.innerHTML = `<span class="closed-tag">⚪ Closed</span> Opens ${info.next_open} · <span class="countdown" id="countdown"></span>`;
    }
    startCountdown(info.time_left_secs);
  }

  if (sgx) {
    if (info.sgx_nifty) {
      sgx.innerHTML = `SGX Nifty: <strong>${info.sgx_nifty.toLocaleString()}</strong>`;
    } else {
      sgx.innerHTML = `SGX Nifty: <span style="color:#555">unavailable</span>`;
    }
  }
}

function startCountdown(secs) {
  if (timerInterval) clearInterval(timerInterval);
  if (secs === null || secs === undefined) return;

  function update() {
    const el = document.getElementById('countdown');
    if (!el) return;
    if (secs <= 0) {
      el.textContent = 'Opening now...';
      checkMarket();
      return;
    }
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    el.textContent = h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
    secs--;
  }
  update();
  timerInterval = setInterval(update, 1000);
}

function parseSignal(sig) {

function parseSignal(sig) {
  if (!sig) return '<div class="empty">No signal data available. Click "Fetch Latest Data" during market hours.</div>';
  
  const emoji = {BULLISH:'🟢',BEARISH:'🔴',NEUTRAL:'🟡',SIDEWAYS:'🟠'}[sig.signal]||'⚪';
  const pcr = sig.pcr_total || 0;
  const pcrColor = pcr > 1.2 ? 'green' : pcr < 0.8 ? 'red' : 'cyan';
  
  const range = sig.spot_range_today || {};
  const resistance = Array.isArray(sig.key_resistance) ? sig.key_resistance.join(', ') : (sig.key_resistance || '-');
  const support = Array.isArray(sig.key_support) ? sig.key_support.join(', ') : (sig.key_support || '-');
  
  return `
<div class="signal-card">
<div class="signal-header">
<span class="signal-badge ${sig.signal}">${emoji} ${sig.signal}</span>
<span class="confidence">🔥 ${sig.confidence || '?'} Confidence</span>
</div>
<div class="metrics">
<div class="metric"><div class="label">ATM Strike</div><div class="val cyan">${sig.atm || '-'}</div></div>
<div class="metric"><div class="label">Max Pain</div><div class="val">${sig.max_pain || '-'}</div></div>
<div class="metric"><div class="label">PCR Total</div><div class="val ${pcrColor}">${pcr || '-'}</div></div>
<div class="metric"><div class="label">PCR Near ATM</div><div class="val">${sig.pcr_near_atm || '-'}</div></div>
<div class="metric"><div class="label">Total CE OI</div><div class="val">${(sig.total_ce_oi||0).toLocaleString()}</div></div>
<div class="metric"><div class="label">Total PE OI</div><div class="val">${(sig.total_pe_oi||0).toLocaleString()}</div></div>
</div>
<div class="metrics">
<div class="metric"><div class="label">📈 Range Low</div><div class="val cyan">${range.low || '-'}</div></div>
<div class="metric"><div class="label">📉 Range High</div><div class="val cyan">${range.high || '-'}</div></div>
<div class="metric"><div class="label">🛡️ Support</div><div class="val green">${support}</div></div>
<div class="metric"><div class="label">🚧 Resistance</div><div class="val red">${resistance}</div></div>
</div>
<div class="strategy">
<h3>📌 Suggested Strategy</h3>
<div class="strategy-text">${sig.suggested_strategy || '-'}</div>
</div>
<div class="notes">
<div class="note"><h4>PCR Interpretation</h4><p>${sig.pcr_interpretation || '-'}</p></div>
<div class="note"><h4>OI Story</h4><p>${sig.oi_story || '-'}</p></div>
</div>
<div class="note" style="margin-bottom:15px"><h4>Max Pain Bias</h4><p>${sig.max_pain_bias || '-'}</p></div>
<div class="invalidate">❌ Invalidation: ${sig.invalidation || '-'}</div>
<div class="summary"><p>${sig.summary || '-'}</p></div>
</div>
`;
}

function renderHistory(signals) {
  const grid = document.getElementById('histGrid');
  if (!signals || signals.length === 0) {
    grid.innerHTML = '<div class="empty" style="padding:20px">No history yet</div>';
    return;
  }
  grid.innerHTML = signals.map(s => {
    const cls = s.signal ? s.signal.toLowerCase().replace(' ','') : 'neutral';
    const ts = s.timestamp ? new Date(s.timestamp).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'}) : '-';
    return `<div class="hist-row ${cls}"><span class="ts">${ts}</span><span class="val">${s.signal||'?'}</span></div>`;
  }).join('');
}

async function fetchSignal() {
  const area = document.getElementById('signalArea');
  area.innerHTML = '<div class="loading"><div class="spinner"></div>Generating signal...</div>';
  try {
    const r = await fetch(BACKEND_URL + '/api/signal/' + currentSym);
    const data = await r.json();
    if (data.error) { area.innerHTML = `<div class="empty">${data.error}</div>`; return; }
    lastSignal = data;
    area.innerHTML = parseSignal(data);
    document.getElementById('lastUpdate').textContent = `Last update: ${new Date().toLocaleString('en-IN')}`;
    // Load history
    const hr = await fetch(BACKEND_URL + '/api/history/' + currentSym);
    const hist = await hr.json();
    renderHistory(hist);
  } catch(e) {
    area.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

async function runPoll() {
  const area = document.getElementById('signalArea');
  area.innerHTML = '<div class="loading"><div class="spinner"></div>Fetching latest data from NSE...</div>';
  try {
    const r = await fetch(BACKEND_URL + '/api/poll?symbol=' + currentSym, {method:'POST'});
    const data = await r.json();
    if (data.error) { area.innerHTML = `<div class="empty">${data.error}</div>`; return; }
    await fetchSignal();
  } catch(e) {
    area.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

async function checkMarket() {
  try {
    const r = await fetch(BACKEND_URL + '/api/status');
    const d = await r.json();
    setStatus(d.market_open);
  } catch {}
}

// Symbol switching
document.querySelectorAll('.sym-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sym-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentSym = btn.dataset.sym;
    fetchSignal();
  });
});

// Start clock
function updateClock() {
  const el = document.getElementById('clock');
  if (el && marketInfo) {
    el.textContent = marketInfo.current_date_ist + ' · IST';
  }
}
setInterval(updateClock, 1000);

// Chat
let chatHistory = [];

function toggleChat() {
  const panel = document.getElementById('chatPanel');
  const fab = document.getElementById('chatFab');
  panel.classList.toggle('open');
  fab.textContent = panel.classList.contains('open') ? '×' : '💬';
}

function appendMsg(content, role, cls) {
  const msgs = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg ' + (cls || role);
  div.textContent = content;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  appendMsg(msg, 'user');
  const loading = appendMsg('Thinking...', 'bot', 'loading');

  try {
    const r = await fetch(BACKEND_URL + '/api/chat?' + new URLSearchParams({message: msg, history: JSON.stringify(chatHistory)}));
    const d = await r.json();
    loading.remove();
    if (d.error) {
      appendMsg(d.error, 'bot', 'error');
    } else {
      appendMsg(d.response, 'bot');
      chatHistory.push({role: 'user', content: msg});
      chatHistory.push({role: 'model', content: d.response});
    }
  } catch(e) {
    loading.remove();
    appendMsg('Error: ' + e.message, 'bot', 'error');
  }
}

// Start
checkMarket();
fetchSignal();
setInterval(updateClock, 1000);
setInterval(checkMarket, 30000);
</script>
</body>
</html>
"""


def get_latest_signal(symbol: str = "NIFTY") -> dict | None:
    if not Path(DB).exists():
        return None
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT timestamp, signal_json FROM signals WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    conn.close()
    if row and row[1]:
        try:
            return json.loads(row[1])
        except:
            return None
    return None


def get_history(symbol: str = "NIFTY", limit: int = 50) -> list:
    if not Path(DB).exists():
        return []
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT timestamp, signal, confidence FROM signals WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
        (symbol, limit)
    ).fetchall()
    conn.close()
    return [{"timestamp": r[0], "signal": r[1], "confidence": r[2]} for r in rows]


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML


@app.get("/api/status")
async def status(request: Request):
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=30):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
    info = get_market_info()
    sgx = get_sgx_nifty()
    return {
        **info,
        "sgx_nifty": sgx,
        "sgx_source": "SGX" if sgx else None,
    }


@app.post("/api/poll")
async def poll(request: Request, symbol: str = Query("NIFTY"), force: bool = Query(False)):
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=10, window=60):
        return JSONResponse({"error": "Rate limit exceeded — max 10 polls/minute"}, status_code=429)
    import subprocess, sys
    env = {**os.environ}
    if force:
        env["FORCE"] = "1"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "nse_poller.py"), "--symbol", symbol, "--export"],
        capture_output=True, text=True, env=env
    )
    return {"ok": True, "output": result.stdout[-1000:], "stderr": result.stderr[-500:]}


@app.get("/api/signal/{symbol}")
async def get_signal(request: Request, symbol: str = "NIFTY"):
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=30):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from engine.signal_engine import get_signal as engine_signal, save_signal as engine_save
        sig = engine_signal(symbol)
        engine_save(symbol)

        if sig.get("signal") == "NO_DATA":
            return JSONResponse({"error": "No data yet. Fetch during market hours (09:15–15:30 IST)."}, status_code=404)

        return sig
    except Exception as e:
        return JSONResponse({"error": f"Error: {str(e)}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Error generating signal: {str(e)}"}, status_code=500)


@app.get("/api/history/{symbol}")
async def history(request: Request, symbol: str = "NIFTY"):
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=30):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
    return get_history(symbol)


@app.get("/api/snapshots/{symbol}")
async def snapshots(request: Request, symbol: str = "NIFTY"):
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=20):
        return JSONResponse({"error": "Rate limit exceeded"}, status_code=429)
    if not Path(DB).exists():
        return []
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT timestamp FROM snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    if not row:
        conn.close()
        return []
    ts = row[0]
    rows = conn.execute(
        "SELECT strike, option_type, oi, change_oi, volume, iv, ltp, change, bid, ask FROM snapshots WHERE symbol = ? AND timestamp = ? ORDER BY strike",
        (symbol, ts)
    ).fetchall()
    conn.close()
    by_strike = {}
    for r in rows:
        s, opt, oi, coi, vol, iv, ltp, chg, bid, ask = r
        if s not in by_strike:
            by_strike[s] = {}
        by_strike[s][opt] = {"oi": oi, "coi": coi, "vol": vol, "iv": iv, "ltp": ltp, "chg": chg, "bid": bid, "ask": ask}
    return {"timestamp": ts, "strikes": by_strike}


@app.post("/api/chat")
async def chat(request: Request, message: str = Query(...), history: str = Query("[]")):
    """Chat with Gemini about the NSE option chain data"""
    check_api_key(request)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limit(client_ip, limit=10, window=60):
        return JSONResponse({"error": "Rate limit exceeded — max 10 chats/minute"}, status_code=429)

    if not GEMINI_KEY:
        return JSONResponse({"error": "GEMINI_KEY not configured."}, status_code=500)

    import csv as csvmod

    # Build context from CSV if available
    context = ""
    csv_path = Path(__file__).parent / "option-chain.csv"
    if csv_path.exists():
        with open(csv_path) as f:
            reader = csvmod.reader(f)
            lines = list(reader)
        if len(lines) >= 3:
            headers = lines[1]
            context = "Option Chain Data:\n" + "\n".join([",".join(map(str, l)) for l in lines[2:20]]) + "\n\nHeaders: " + ",".join(headers)

    # Build chat history
    try:
        chat_history = json.loads(history)
    except:
        chat_history = []

    system_prompt = f"""You are an expert NSE F&O options analyst. Be concise and direct. Focus on:
- Option chain analysis (OI buildup, max pain, PCR, IV skew)
- Trade setup suggestions with specific strikes
- Risk management
- Market sentiment interpretation

Current option chain data:
{context}
"""

    messages = [{"role": "user", "parts": [{"text": system_prompt}]}] if system_prompt.strip() != "" else []
    for h in chat_history[-10:]:
        messages.append({"role": h.get("role", "user"), "parts": [{"text": h.get("content", "")}]})
    messages.append({"role": "user", "parts": [{"text": message}]})

    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}'
    payload = {"contents": messages, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024}}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            text = result['candidates'][0]['content']['parts'][0]['text']
            return {"response": text}
    except urllib.error.HTTPError as e:
        return JSONResponse({"error": f"API Error {e.code}: {e.read().decode()}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


try:
    from broker_routes import broker_router
    app.include_router(broker_router, prefix="/api/broker")
except ImportError:
    pass


if __name__ == "__main__":
    print("🌐 Starting NSE Signal Web UI at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)