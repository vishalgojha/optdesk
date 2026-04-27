'use client';

import { useState, useEffect, useRef } from 'react';

// ── Types ────────────────────────────────────────────────────────────────

interface MarketInfo {
  is_open: boolean;
  is_weekend: boolean;
  current_time_ist: string;
  current_date_ist: string;
  market_open_time: string;
  market_close_time: string;
  next_open: string | null;
  time_left_secs: number | null;
  sgx_nifty: number | null;
  sgx_source: string | null;
}

interface Signal {
  signal: string;
  confidence: string;
  spot_range_today: { low: number; high: number };
  key_resistance: number[];
  key_support: number[];
  max_pain_bias: string;
  pcr_interpretation: string;
  oi_story: string;
  suggested_strategy: string;
  invalidation: string;
  summary: string;
  atm: number;
  max_pain: number;
  pcr_total: number;
  pcr_near_atm: number;
  total_ce_oi: number;
  total_pe_oi: number;
}

// ── Market Status Bar ────────────────────────────────────────────────────

function getTimeLeft(secs: number | null): string {
  if (secs === null || secs <= 0) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

function formatCountdown(secs: number | null): string {
  if (secs === null) return '';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function MarketStatus({ info }: { info: MarketInfo | null }) {
  const [countdown, setCountdown] = useState('');

  useEffect(() => {
    if (!info) return;
    const update = () => {
      if (info.is_open && info.time_left_secs !== null) {
        const remaining = Math.max(0, info.time_left_secs - Math.floor((Date.now() / 1000) % 86400));
        const now = new Date();
        const closeTime = new Date(now);
        closeTime.setHours(15, 30, 0, 0);
        if (now > closeTime) return;
        const diff = Math.floor((closeTime.getTime() - now.getTime()) / 1000);
        setCountdown(formatCountdown(diff));
      } else if (!info.is_open && info.time_left_secs !== null) {
        setCountdown(getTimeLeft(info.time_left_secs));
      }
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [info]);

  if (!info) return <div style={{ color: '#555' }}>Checking market...</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.9rem' }}>
        <div style={{
          width: 10, height: 10, borderRadius: '50%',
          background: info.is_open ? '#44ff88' : '#ff4444',
          boxShadow: info.is_open ? '0 0 10px #44ff88' : '0 0 10px #ff4444',
          animation: info.is_open ? 'pulse 2s infinite' : 'none',
        }} />
        {info.is_open ? (
          <span style={{ color: '#44ff88', fontWeight: 600 }}>
            🔴 LIVE · Closes {info.market_close_time} · {countdown && <span style={{ color: '#00d4ff' }}>{countdown}</span>}
          </span>
        ) : (
          <span style={{ color: '#888' }}>
            {info.is_weekend ? '⏰ Weekend' : '⚪ Closed'} · {info.next_open ? `Opens ${info.next_open}` : ''}
            {countdown && <span style={{ color: '#00d4ff', marginLeft: 8 }}>{countdown}</span>}
          </span>
        )}
      </div>
      {info.sgx_nifty && (
        <div style={{ fontSize: '0.8rem', color: '#888' }}>
          SGX Nifty: <strong style={{ color: '#00d4ff' }}>{info.sgx_nifty.toLocaleString()}</strong>
        </div>
      )}
      <div style={{ fontSize: '0.75rem', color: '#555' }}>
        {info.current_time_ist} IST · {info.current_date_ist}
      </div>
    </div>
  );
}

// ── Symbol Selector ──────────────────────────────────────────────────────

const SYMBOLS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];

function SymbolSelector({ sym, onChange }: { sym: string; onChange: (s: string) => void }) {
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
      {SYMBOLS.map(s => (
        <button
          key={s}
          onClick={() => onChange(s)}
          style={{
            padding: '8px 20px',
            background: sym === s ? '#2a2a5a' : '#1a1a3a',
            border: `1px solid ${sym === s ? '#00d4ff' : '#3a3a6a'}`,
            borderRadius: 8,
            color: sym === s ? '#00d4ff' : '#a0a0c0',
            cursor: 'pointer',
            fontSize: '0.9rem',
            fontWeight: 500,
            boxShadow: sym === s ? '0 0 15px #00d4ff30' : 'none',
            transition: 'all 0.2s',
          }}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

// ── Signal Card ──────────────────────────────────────────────────────────

function SignalBadge({ signal }: { signal: string }) {
  const colors: Record<string, string> = {
    BULLISH: '#003300', BEARISH: '#330000', NEUTRAL: '#333300', SIDEWAYS: '#332200',
  };
  const textColors: Record<string, string> = {
    BULLISH: '#44ff88', BEARISH: '#ff4444', NEUTRAL: '#ffff44', SIDEWAYS: '#ffaa44',
  };
  const emojis: Record<string, string> = {
    BULLISH: '🟢', BEARISH: '🔴', NEUTRAL: '🟡', SIDEWAYS: '🟠',
  };
  return (
    <span style={{
      fontSize: '1.3rem', fontWeight: 700, padding: '6px 16px', borderRadius: 8,
      background: colors[signal] || '#1a1a3a', color: textColors[signal] || '#fff',
    }}>
      {emojis[signal] || '⚪'} {signal}
    </span>
  );
}

function MetricGrid({ sig }: { sig: Signal }) {
  const grid: Array<{ label: string; val: React.ReactNode; cls?: string }> = [
    { label: 'ATM Strike', val: sig.atm?.toLocaleString(), cls: 'cyan' },
    { label: 'Max Pain', val: sig.max_pain?.toLocaleString() },
    { label: 'PCR Total', val: sig.pcr_total?.toFixed(3), cls: sig.pcr_total > 1.2 ? 'green' : sig.pcr_total < 0.8 ? 'red' : 'cyan' },
    { label: 'PCR Near ATM', val: sig.pcr_near_atm?.toFixed(3) },
    { label: 'Total CE OI', val: (sig.total_ce_oi || 0).toLocaleString() },
    { label: 'Total PE OI', val: (sig.total_pe_oi || 0).toLocaleString() },
    { label: 'Range Low', val: sig.spot_range_today?.low?.toLocaleString(), cls: 'cyan' },
    { label: 'Range High', val: sig.spot_range_today?.high?.toLocaleString(), cls: 'cyan' },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
      {grid.map(m => (
        <div key={m.label} style={{
          background: '#0a0a1a', border: '1px solid #1a1a3a', borderRadius: 8, padding: 12, textAlign: 'center',
        }}>
          <div style={{ fontSize: '0.7rem', color: '#666', textTransform: 'uppercase', letterSpacing: 1 }}>{m.label}</div>
          <div style={{
            fontSize: '1.2rem', fontWeight: 600, marginTop: 4,
            color: m.cls === 'green' ? '#44ff88' : m.cls === 'red' ? '#ff4444' : m.cls === 'cyan' ? '#00d4ff' : '#e0e0f0',
          }}>{m.val || '-'}</div>
        </div>
      ))}
    </div>
  );
}

function SignalCard({ sig }: { sig: Signal }) {
  return (
    <div style={{ background: '#12122a', border: '1px solid #2a2a4a', borderRadius: 12, padding: 25, marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 15, flexWrap: 'wrap', gap: 10 }}>
        <SignalBadge signal={sig.signal} />
        <span style={{ padding: '4px 12px', background: '#1a1a3a', borderRadius: 20, fontSize: '0.85rem', color: '#a0a0c0' }}>
          🔥 {sig.confidence} Confidence
        </span>
      </div>

      <MetricGrid sig={sig} />

      <div style={{ background: '#0f0f2a', border: '1px solid #00d4ff30', borderRadius: 8, padding: 15, marginBottom: 15 }}>
        <div style={{ fontSize: '0.9rem', color: '#00d4ff', marginBottom: 8, fontWeight: 600 }}>📌 Suggested Strategy</div>
        <div style={{ fontSize: '1.1rem', fontWeight: 500, color: '#fff' }}>{sig.suggested_strategy}</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 15, marginBottom: 15 }}>
        <div style={{ background: '#0a0a1a', borderRadius: 8, padding: 15 }}>
          <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: 6, textTransform: 'uppercase' }}>🛡️ Support</div>
          <div style={{ color: '#44ff88', fontWeight: 600 }}>{sig.key_support?.join(', ') || '-'}</div>
        </div>
        <div style={{ background: '#0a0a1a', borderRadius: 8, padding: 15 }}>
          <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: 6, textTransform: 'uppercase' }}>🚧 Resistance</div>
          <div style={{ color: '#ff4444', fontWeight: 600 }}>{sig.key_resistance?.join(', ') || '-'}</div>
        </div>
      </div>

      <div style={{ background: '#0a0a1a', borderRadius: 8, padding: 15, marginBottom: 15 }}>
        <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: 6, textTransform: 'uppercase' }}>PCR Interpretation</div>
        <div style={{ fontSize: '0.9rem', lineHeight: 1.5, color: '#b0b0d0' }}>{sig.pcr_interpretation}</div>
      </div>

      <div style={{ background: '#0a0a1a', borderRadius: 8, padding: 15, marginBottom: 15 }}>
        <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: 6, textTransform: 'uppercase' }}>OI Story</div>
        <div style={{ fontSize: '0.9rem', lineHeight: 1.5, color: '#b0b0d0' }}>{sig.oi_story}</div>
      </div>

      <div style={{ background: '#1a0a0a', border: '1px solid #ff444440', borderLeft: '3px solid #ff4444', borderRadius: 8, padding: 12, marginBottom: 15, fontSize: '0.9rem', color: '#ff8888' }}>
        ❌ Invalidation: {sig.invalidation}
      </div>

      <div style={{ background: '#0a0a1a', borderRadius: 8, padding: 15, textAlign: 'center' }}>
        <div style={{ fontSize: '1.3rem', fontWeight: 600, color: '#fff' }}>{sig.summary}</div>
      </div>
    </div>
  );
}

// ── Chat ─────────────────────────────────────────────────────────────────

function ChatBox() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([
    { role: 'model', content: 'Hi! Ask me anything about NSE options, signals, or trading strategies.' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<Array<{ role: string; content: string }>>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

const DISCLAIMER = "⚠️ DISCLAIMER: Signals are for educational purposes only. NOT financial advice. Options trading involves substantial risk of loss.";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput('');
    setMessages(m => [...m, { role: 'user', content: msg }]);
    setLoading(true);

    try {
      const res = await fetch(`/api/chat?message=${encodeURIComponent(msg)}&history=${encodeURIComponent(JSON.stringify(history))}`);
      const data = await res.json();
      if (data.error) {
        setMessages(m => [...m, { role: 'model', content: `❌ ${data.error}` }]);
      } else {
        setMessages(m => [...m, { role: 'model', content: data.response }]);
        setHistory(h => [...h, { role: 'user', content: msg }, { role: 'model', content: data.response }]);
      }
    } catch (e: any) {
      setMessages(m => [...m, { role: 'model', content: `❌ Error: ${e.message}` }]);
    }
    setLoading(false);
  };

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        style={{
          position: 'fixed', bottom: 24, right: open ? 32 : 24,
          width: 56, height: 56, borderRadius: '50%',
          background: '#00d4ff', border: 'none', cursor: 'pointer',
          fontSize: '1.5rem', boxShadow: '0 4px 20px #00d4ff60',
          transition: 'all 0.3s', zIndex: 999,
        }}
      >
        {open ? '×' : '💬'}
      </button>

      {open && (
        <div style={{
          position: 'fixed', bottom: 90, right: 24, width: 380, maxWidth: 'calc(100vw - 40px)',
          height: 520, background: '#12122a', border: '1px solid #2a2a4a', borderRadius: 16,
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
          boxShadow: '0 8px 40px #00000080', zIndex: 998, animation: 'slideUp 0.3s ease',
        }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '14px 16px', background: '#1a1a3a', borderBottom: '1px solid #2a2a4a',
            fontWeight: 600, color: '#00d4ff',
          }}>
            AI Analyst
            <button onClick={() => setOpen(false)} style={{ background: 'none', border: 'none', color: '#666', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {messages.map((m, i) => (
              <div
                key={i}
                style={{
                  maxWidth: '85%', padding: '10px 14px', borderRadius: 12, fontSize: '0.9rem', lineHeight: 1.4, wordBreak: 'break-word',
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  background: m.role === 'user' ? '#00d4ff20' : '#1a1a3a',
                  border: `1px solid ${m.role === 'user' ? '#00d4ff40' : '#2a2a4a'}`,
                  color: m.role === 'user' ? '#00d4ff' : '#c0c0e0',
                }}
              >
                {m.content}
              </div>
            ))}
            {loading && (
              <div style={{ maxWidth: '85%', padding: '10px 14px', borderRadius: 12, alignSelf: 'flex-start', color: '#555', fontStyle: 'italic', fontSize: '0.9rem' }}>
                Thinking...
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #2a2a4a', background: '#0a0a1a' }}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && send()}
              placeholder="Ask about options, signals, strategies..."
              style={{
                flex: 1, background: '#1a1a3a', border: '1px solid #2a2a4a', borderRadius: 8,
                padding: '10px 12px', color: '#e0e0f0', fontSize: '0.9rem', outline: 'none',
              }}
            />
            <button onClick={send} disabled={loading} style={{
              background: '#00d4ff', border: 'none', borderRadius: 8, padding: '10px 16px',
              cursor: loading ? 'not-allowed' : 'pointer', fontSize: '1rem', opacity: loading ? 0.5 : 1,
            }}>
              ➤
            </button>
          </div>
        </div>
      )}
    </>
  );
}

// ── Refresh Buttons ─────────────────────────────────────────────────────

function ActionButtons({ onPoll, onRefresh }: { onPoll: () => void; onRefresh: () => void }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', gap: 15, marginTop: 20, marginBottom: 10 }}>
      <button onClick={onRefresh} style={{
        padding: '10px 25px', borderRadius: 8, border: 'none',
        background: '#00d4ff', color: '#000', fontSize: '0.9rem', fontWeight: 500, cursor: 'pointer',
        boxShadow: '0 0 20px #00d4ff40',
      }}>
        🔄 Refresh Signal
      </button>
      <button onClick={onPoll} style={{
        padding: '10px 25px', borderRadius: 8, border: '1px solid #3a3a6a',
        background: '#2a2a4a', color: '#a0a0c0', fontSize: '0.9rem', fontWeight: 500, cursor: 'pointer',
      }}>
        📡 Fetch Latest Data
      </button>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────

export default function Home() {
  const [symbol, setSymbol] = useState('NIFTY');
  const [marketInfo, setMarketInfo] = useState<MarketInfo | null>(null);
  const [signal, setSignal] = useState<Signal | null>(null);
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState<Array<{ timestamp: string; signal: string; confidence: string }>>([]);

  const fetchStatus = async () => {
    try {
      const r = await fetch('/api/status');
      setMarketInfo(await r.json());
    } catch {}
  };

  const fetchSignal = async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/signal/${symbol}`);
      if (r.ok) {
        const data = await r.json();
        setSignal(data);
      } else {
        setSignal(null);
      }
    } catch {}
    setLoading(false);
  };

  const fetchHistory = async () => {
    try {
      const r = await fetch(`/api/history/${symbol}`);
      setHistory(await r.json());
    } catch {}
  };

  const runPoll = async () => {
    try {
      await fetch('/api/poll', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      await fetchSignal();
      await fetchHistory();
    } catch {}
  };

  useEffect(() => {
    fetchStatus();
    fetchSignal();
    fetchHistory();
    const t = setInterval(fetchStatus, 30000);
    return () => clearInterval(t);
  }, [symbol]);

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: 20 }}>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}`}</style>

      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 0', borderBottom: '1px solid #2a2a4a', marginBottom: 30, flexWrap: 'wrap', gap: 10 }}>
        <h1 style={{ fontSize: '1.5rem', color: '#00d4ff', textShadow: '0 0 20px #00d4ff40', margin: 0 }}>
          📊 NSE Option Chain Signals
        </h1>
        <MarketStatus info={marketInfo} />
      </header>

      <SymbolSelector sym={symbol} onChange={s => setSymbol(s)} />

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ width: 30, height: 30, border: '3px solid #1a1a3a', borderTopColor: '#00d4ff', borderRadius: '50%', margin: '0 auto 15px', animation: 'spin 1s linear infinite' }} />
          <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
          <div style={{ color: '#00d4ff' }}>Loading signals...</div>
        </div>
      ) : signal ? (
        <SignalCard sig={signal} />
      ) : (
        <div style={{ textAlign: 'center', padding: 60, color: '#555', fontSize: '1rem' }}>
          No signal data yet. Click "Fetch Latest Data" during market hours (09:15–15:30 IST).
        </div>
      )}

      <ActionButtons onPoll={runPoll} onRefresh={fetchSignal} />

      {history.length > 0 && (
        <div style={{ background: '#12122a', border: '1px solid #2a2a4a', borderRadius: 12, padding: 20, marginTop: 20 }}>
          <div style={{ fontSize: '0.9rem', color: '#888', marginBottom: 15 }}>📜 Signal History</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {history.slice(0, 30).map((h, i) => (
              <div key={i} style={{
                background: '#0a0a1a', borderRadius: 6, padding: '8px 12px', fontSize: '0.75rem', textAlign: 'center',
              }}>
                <div style={{ color: '#555', fontSize: '0.65rem' }}>
                  {new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                </div>
                <div style={{
                  fontWeight: 600, marginTop: 3,
                  color: h.signal === 'BULLISH' ? '#44ff88' : h.signal === 'BEARISH' ? '#ff4444' : '#ffff44',
                }}>
                  {h.signal || '?'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{
        marginTop: 24, padding: '12px 16px', background: '#1a0a0a', border: '1px solid #ff444440',
        borderRadius: 8, fontSize: '0.75rem', color: '#ff8888', lineHeight: 1.5,
      }}>
        ⚠️ {DISCLAIMER}
      </div>

      <ChatBox />
    </div>
  );
}