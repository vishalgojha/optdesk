# NSE Option Chain Signals

AI-powered NSE Nifty/BankNifty option chain analysis with real-time signals and historical intelligence.

## Features

- 📊 **Real-time Signals** — PCR, Max Pain, ATM, OI buildup analysis
- 🤖 **AI Chat** — Ask Gemini about options strategies
- 📈 **Historical Intelligence** — 3-month trend analysis
- 🖥️ **Web UI** — React frontend + Python backend

## Quick Start

### 1. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# Node.js
cd app && npm install
```

### 2. Set Environment Variables

Create `.env` file:
```
GEMINI_KEY=your_gemini_api_key_here
```

### 3. Run

**Terminal 1 — Backend:**
```bash
python web_ui.py
```

**Terminal 2 — Frontend:**
```bash
cd app && npm run dev
```

Open http://localhost:3000

## Scripts

| Script | Purpose |
|--------|---------|
| `web_ui.py` | FastAPI backend (port 8000) |
| `nse_poller.py` | Fetch option chain from NSE |
| `nse_intel.py` | Collect historical data |
| `nse_signal.py` | Gemini signal generation |
| `app/` | Next.js React frontend |

## Usage

### Fetch Data (Market Hours: 09:15–15:30 IST)
```bash
python nse_poller.py --export
```

### Historical Intelligence
```bash
# Collect data during market hours
python nse_intel.py --scrape --symbols NIFTY,BANKNIFTY

# Analyze trends
python nse_intel.py --analyze --days 90
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/status` | Market status, SGX Nifty |
| `/api/signal/{symbol}` | Current signal |
| `/api/chat` | AI chat |
| `/api/poll` | Fetch latest data |

## Tech Stack

- **Frontend:** Next.js 15, React 19
- **Backend:** FastAPI, Python 3.11
- **AI:** Gemini 2.0 Flash
- **Data:** nsepython, SQLite

## Deploy

### Vercel (Frontend)
```bash
cd app
vercel deploy
```

### Render/Railway (Backend)
```bash
pip install -r requirements.txt
python web_ui.py
```

## License

MIT
