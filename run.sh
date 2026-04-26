#!/usr/bin/env bash
# NSE Signal Pipeline
# Usage: ./run.sh [--once | --watch]

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERR]${NC} $1"; }

# Check Camofox
check_camofox() {
    curl -s http://localhost:9377/tabs >/dev/null 2>&1
}

# Start Camofox if needed
start_camofox() {
    if check_camofox; then
        log "Camofox already running"
        return 0
    fi
    
    warn "Camofox not running, starting..."
    
    if command -v docker &> /dev/null; then
        docker run -d --name camofox -p 9377:9377 camofox:latest 2>/dev/null || \
        docker start camofox 2>/dev/null || true
        sleep 3
        
        if check_camofox; then
            log "Camofox started via Docker"
            return 0
        fi
    fi
    
    # Try npm
    if [ -d "camofox-browser" ]; then
        warn "Starting Camofox via npm..."
        (cd camofox-browser && npm start &>/dev/null &)
        sleep 5
        
        if check_camofox; then
            log "Camofox started via npm"
            return 0
        fi
    fi
    
    err "Could not start Camofox. Start manually: cd camofox-browser && npm start"
    return 1
}

# Run poller + signal
run_pipeline() {
    log "🔄 Fetching option chain..."
    python3 nse_poller.py --symbol NIFTY --export
    
    if [ -f "option-chain.csv" ]; then
        log "📊 Generating signal..."
        python3 nse_signal.py --file option-chain.csv --key "$GEMINI_KEY"
    else
        err "No CSV generated"
        return 1
    fi
}

# Watch mode
watch() {
    log "🫡 Watch mode: polling every 5 minutes during market hours"
    
    while true; do
        # Check market hours (IST = UTC+5:30)
        HOUR=$(date -u +%H)
        MIN=$(date -u +%M)
        IST_HOUR=$(( (10#$HOUR + 5 + 24) % 24 ))
        
        # 9:15 to 15:30 IST = 03:45 to 10:00 UTC
        if [ "$IST_HOUR" -ge 3 ] && [ "$IST_HOUR" -lt 10 ]; then
            run_pipeline
        else
            warn "Market closed (IST hour: $IST_HOUR)"
        fi
        
        log "⏳ Next poll in 5 minutes..."
        sleep 300
    done
}

# Main
MODE="${1:-once}"

case "$MODE" in
    --once)
        start_camofox
        run_pipeline
        ;;
    --watch)
        watch
        ;;
    --help|-h)
        echo "Usage: $0 [--once|--watch]"
        echo "  --once   Run once (default)"
        echo "  --watch  Continuous polling"
        ;;
    *)
        err "Unknown option: $MODE"
        echo "Use --help for usage"
        exit 1
        ;;
esac