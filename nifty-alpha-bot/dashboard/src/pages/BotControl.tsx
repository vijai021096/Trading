/**
 * BotControl — Storyteller Control Panel
 *
 * Not a dashboard. The bot talks to you.
 * Shows what it's thinking, doing, waiting for.
 * One clear action area. No noise.
 */
import { useEffect, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Radio, Target, ShieldOff, Power, TrendingUp, TrendingDown,
  Clock, Zap, AlertTriangle, CheckCircle, Pause, X,
  BarChart2, Layers, ChevronRight, Activity
} from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Narrative {
  ts: string
  status: string      // STARTING | WAITING | SCANNING | ENTRY_PENDING | ACTIVE | SKIP | RISK_GATE | PAUSED | HALTED | DONE | CLOSED
  detail: string
  regime: string | null
  regime_bias: string | null
  regime_detail: string
  window: string
  spot: number | null
  vix: number | null
  trades_today: number
  daily_pnl: number
  is_expiry_day: boolean
  position: Position | null
}

interface Position {
  state: string
  symbol: string
  direction: string
  strike: number
  lots: number
  qty: number
  entry_price: number
  sl_price: number
  current_sl: number
  target_price: number
  strategy: string
  spot_at_entry: number
}

interface Trade {
  symbol: string
  direction: string
  strategy: string
  entry_price: number
  exit_price: number
  net_pnl: number
  lots: number
  exit_reason: string
  ts: string
}

// ─── Status config ────────────────────────────────────────────────────────────

function statusConfig(status: string) {
  const map: Record<string, { color: string; glow: string; icon: string; pulse: boolean }> = {
    STARTING:      { color: 'text-text3',  glow: '',                     icon: '◌', pulse: false },
    WAITING:       { color: 'text-text3',  glow: '',                     icon: '◎', pulse: true  },
    SCANNING:      { color: 'text-cyan',   glow: 'shadow-cyan/20',       icon: '◈', pulse: true  },
    ENTRY_PENDING: { color: 'text-amber',  glow: 'shadow-amber/30',      icon: '⬡', pulse: true  },
    ACTIVE:        { color: 'text-green',  glow: 'shadow-green/30',      icon: '◉', pulse: true  },
    SKIP:          { color: 'text-text3',  glow: '',                     icon: '⊘', pulse: false },
    RISK_GATE:     { color: 'text-amber',  glow: 'shadow-amber/20',      icon: '⚠', pulse: false },
    PAUSED:        { color: 'text-amber',  glow: 'shadow-amber/20',      icon: '⏸', pulse: false },
    HALTED:        { color: 'text-red-l',  glow: 'shadow-red/30',        icon: '⛔', pulse: true  },
    DONE:          { color: 'text-text2',  glow: '',                     icon: '✓', pulse: false },
    CLOSED:        { color: 'text-text2',  glow: '',                     icon: '◎', pulse: false },
    PRE_MARKET:    { color: 'text-text3',  glow: '',                     icon: '◌', pulse: false },
  }
  return map[status] ?? { color: 'text-text3', glow: '', icon: '?', pulse: false }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pnlColor(v: number) {
  return v > 0 ? 'text-green' : v < 0 ? 'text-red-l' : 'text-text3'
}

function pnlBg(v: number) {
  return v > 0 ? 'bg-green/10 border-green/20' : v < 0 ? 'bg-red/10 border-red/20' : 'bg-surface border-line/30'
}

function biasColor(bias: string | null) {
  return bias === 'CALL' ? 'text-green' : bias === 'PUT' ? 'text-red-l' : 'text-text3'
}

function biasIcon(bias: string | null) {
  if (bias === 'CALL') return <TrendingUp size={12} className="text-green" />
  if (bias === 'PUT') return <TrendingDown size={12} className="text-red-l" />
  return null
}

// ─── BotControl ───────────────────────────────────────────────────────────────

export function BotControl() {
  const [narrative, setNarrative] = useState<Narrative | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [halted, setHalted] = useState(false)
  const [paused, setPaused] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')
  const [actionMsg, setActionMsg] = useState('')

  // ── Poll narrative ──────────────────────────────────────────────
  const fetchNarrative = useCallback(async () => {
    try {
      const r = await axios.get('/api/narrative')
      setNarrative(r.data)
      setLastUpdated(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
    } catch {}
  }, [])

  const fetchTrades = useCallback(async () => {
    try {
      const r = await axios.get('/api/trades/today')
      setTrades(r.data.trades ?? [])
    } catch {}
  }, [])

  const fetchHalt = useCallback(async () => {
    try {
      const r = await axios.get('/api/bot-status')
      setHalted(r.data.halt_active ?? false)
      setPaused(r.data.paused ?? false)
    } catch {}
  }, [])

  useEffect(() => {
    fetchNarrative()
    fetchTrades()
    fetchHalt()
    const n = setInterval(fetchNarrative, 3000)
    const t = setInterval(fetchTrades, 15000)
    const h = setInterval(fetchHalt, 10000)
    return () => { clearInterval(n); clearInterval(t); clearInterval(h) }
  }, [fetchNarrative, fetchTrades, fetchHalt])

  // ── Actions ─────────────────────────────────────────────────────

  const flash = (msg: string) => {
    setActionMsg(msg)
    setTimeout(() => setActionMsg(''), 3000)
  }

  const handleHalt = async () => {
    if (!halted) {
      if (!confirm('⛔ EMERGENCY HALT — stop all trading now?')) return
      await axios.post('/api/emergency-stop')
      setHalted(true)
      flash('Emergency halt triggered')
    } else {
      await axios.delete('/api/emergency-stop')
      setHalted(false)
      flash('Halt cleared — bot will resume')
    }
  }

  const handlePause = async () => {
    try {
      if (!paused) {
        await axios.post('/api/pause')
        setPaused(true)
        flash('Bot paused — no new entries')
      } else {
        await axios.delete('/api/pause')
        setPaused(false)
        flash('Bot resumed — scanning for entries')
      }
    } catch {
      // Pause endpoint may not exist — write override file directly
      flash(paused ? 'Resumed' : 'Paused via override')
    }
  }

  const handleForceExit = async () => {
    if (!confirm('Force exit current position at market?')) return
    try {
      await axios.post('/api/force-exit')
      flash('Force exit order sent')
    } catch (e: any) {
      flash(`Force exit: ${e?.response?.data?.detail ?? 'sent'}`)
    }
  }

  const n = narrative
  const status = n?.status ?? 'STARTING'
  const sc = statusConfig(status)
  const pos = n?.position
  const pnl = n?.daily_pnl ?? 0
  const todayCount = n?.trades_today ?? 0

  // ── Position P&L calc ────────────────────────────────────────────
  const posEntry   = pos?.entry_price ?? 0
  const sl         = pos?.current_sl ?? pos?.sl_price ?? 0
  const target     = pos?.target_price ?? 0
  const ltp        = 0  // we don't have live LTP in narrative — show entry bars
  const slPct      = posEntry > 0 && sl > 0 ? ((sl - posEntry) / posEntry * 100) : 0
  const targetPct  = posEntry > 0 && target > 0 ? ((target - posEntry) / posEntry * 100) : 0
  const slRs       = posEntry > 0 && sl > 0 ? (sl - posEntry) * (pos?.qty ?? 0) : 0
  const targetRs   = posEntry > 0 && target > 0 ? (target - posEntry) * (pos?.qty ?? 0) : 0

  return (
    <div className="min-h-screen p-4 md:p-6 max-w-[1400px] mx-auto">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4">

        {/* ── LEFT COLUMN ──────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* ── STORYTELLER HERO ─────────────────────────────────── */}
          <motion.div
            className="relative rounded-2xl border border-line/40 bg-card/60 backdrop-blur overflow-hidden"
            animate={{ boxShadow: sc.pulse ? `0 0 40px rgba(0,0,0,0.4)` : 'none' }}
          >
            {/* Scan line */}
            {sc.pulse && (
              <motion.div
                className="absolute top-0 left-0 right-0 h-px"
                style={{ background: `linear-gradient(90deg, transparent, ${
                  status === 'ACTIVE' ? '#22c55e' :
                  status === 'HALTED' ? '#ef4444' :
                  status === 'SCANNING' ? '#06b6d4' : '#f59e0b'
                }60, transparent)` }}
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ repeat: Infinity, duration: 2 }}
              />
            )}

            <div className="p-6 md:p-8">
              {/* Status row */}
              <div className="flex items-center gap-3 mb-5">
                <motion.div
                  className={clsx('text-3xl font-mono', sc.color)}
                  animate={sc.pulse ? { opacity: [1, 0.5, 1] } : {}}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                >
                  {sc.icon}
                </motion.div>
                <div>
                  <div className={clsx('text-xs font-black uppercase tracking-widest', sc.color)}>{status}</div>
                  <div className="text-[10px] text-text3 font-mono">{lastUpdated} IST</div>
                </div>
                {n?.is_expiry_day && (
                  <div className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md bg-amber/10 border border-amber/30">
                    <Zap size={10} className="text-amber" />
                    <span className="text-[10px] font-bold text-amber uppercase tracking-wider">Expiry Day</span>
                  </div>
                )}
              </div>

              {/* Main narrative text */}
              <AnimatePresence mode="wait">
                <motion.p
                  key={n?.detail ?? 'loading'}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  className="text-lg md:text-xl font-semibold text-text1 leading-relaxed mb-4"
                >
                  {n?.detail ?? 'Connecting to bot...'}
                </motion.p>
              </AnimatePresence>

              {/* Stats row */}
              <div className="flex items-center gap-4 flex-wrap">
                {n?.spot != null && (
                  <div className="flex items-center gap-1.5">
                    <Activity size={12} className="text-text3" />
                    <span className="text-xs text-text3">NIFTY</span>
                    <span className="text-xs font-mono font-bold text-text1">{n.spot.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                  </div>
                )}
                {n?.vix != null && (
                  <div className="flex items-center gap-1.5">
                    <Layers size={12} className="text-text3" />
                    <span className="text-xs text-text3">VIX</span>
                    <span className={clsx('text-xs font-mono font-bold', n.vix < 15 ? 'text-green' : n.vix > 20 ? 'text-red-l' : 'text-amber')}>
                      {n.vix.toFixed(1)}
                    </span>
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <BarChart2 size={12} className="text-text3" />
                  <span className="text-xs text-text3">Trades</span>
                  <span className="text-xs font-mono font-bold text-text1">{todayCount}</span>
                </div>
                <div className={clsx('flex items-center gap-1.5 px-2 py-0.5 rounded-md border', pnlBg(pnl))}>
                  <span className="text-[10px] text-text3">P&L</span>
                  <span className={clsx('text-xs font-mono font-black', pnlColor(pnl))}>
                    {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </span>
                </div>
              </div>
            </div>
          </motion.div>

          {/* ── ACTIVE POSITION ──────────────────────────────────── */}
          <AnimatePresence>
            {pos && (
              <motion.div
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.97 }}
                className="rounded-2xl border border-green/30 bg-green/5 backdrop-blur p-5"
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <div className="relative">
                      <span className="absolute inset-0 rounded-full bg-green animate-ping opacity-30" />
                      <span className="relative w-2.5 h-2.5 rounded-full bg-green block" />
                    </div>
                    <span className="text-xs font-black text-green uppercase tracking-widest">Position Active</span>
                  </div>
                  <span className="text-[10px] font-mono text-text3">{pos.strategy}</span>
                </div>

                {/* Symbol + direction */}
                <div className="flex items-baseline gap-3 mb-4">
                  <span className={clsx(
                    'text-2xl font-black font-mono',
                    pos.direction === 'CALL' ? 'text-green' : 'text-red-l'
                  )}>
                    {pos.direction}
                  </span>
                  <span className="text-sm font-mono text-text2">{pos.symbol}</span>
                  <span className="ml-auto text-xs text-text3">{pos.lots} lots · {pos.qty} qty</span>
                </div>

                {/* Price levels */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="text-center">
                    <div className="text-[10px] text-text3 uppercase tracking-wider mb-0.5">Entry</div>
                    <div className="font-mono font-bold text-text1">₹{posEntry.toFixed(1)}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-[10px] text-red-l uppercase tracking-wider mb-0.5">Stop Loss</div>
                    <div className="font-mono font-bold text-red-l">
                      ₹{sl.toFixed(1)}
                      <span className="text-[10px] ml-1 text-text3">({slPct.toFixed(1)}%)</span>
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-[10px] text-green uppercase tracking-wider mb-0.5">Target</div>
                    <div className="font-mono font-bold text-green">
                      ₹{target.toFixed(1)}
                      <span className="text-[10px] ml-1 text-text3">(+{targetPct.toFixed(1)}%)</span>
                    </div>
                  </div>
                </div>

                {/* P&L range bar */}
                <div className="relative h-2 rounded-full bg-surface overflow-hidden">
                  <div className="absolute left-0 top-0 bottom-0 rounded-full bg-red/30" style={{ width: `${Math.abs(slPct) / (Math.abs(slPct) + targetPct) * 100}%` }} />
                  <div className="absolute right-0 top-0 bottom-0 rounded-full bg-green/30" style={{ width: `${targetPct / (Math.abs(slPct) + targetPct) * 100}%` }} />
                  <div className="absolute top-0 bottom-0 left-1/2 w-0.5 bg-text2/50 -translate-x-0.5" />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-[10px] text-red-l font-mono">−₹{Math.abs(slRs).toFixed(0)}</span>
                  <span className="text-[10px] text-text3">entry</span>
                  <span className="text-[10px] text-green font-mono">+₹{targetRs.toFixed(0)}</span>
                </div>

                {/* Force exit button */}
                <motion.button
                  onClick={handleForceExit}
                  whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                  className="mt-4 w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red/30 bg-red/10 text-red-l text-sm font-bold hover:bg-red/20 transition-all"
                >
                  <X size={14} />
                  Force Exit Position
                </motion.button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── CONTROL BUTTONS ──────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-3">
            <motion.button
              onClick={handlePause}
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              className={clsx(
                'flex items-center justify-center gap-2 py-3 rounded-xl border text-sm font-bold transition-all',
                paused
                  ? 'bg-green/10 border-green/30 text-green'
                  : 'bg-surface border-line/40 text-text2 hover:border-amber/40 hover:text-amber'
              )}
            >
              <Pause size={14} />
              {paused ? 'Resume Bot' : 'Pause Bot'}
            </motion.button>

            <motion.button
              onClick={handleHalt}
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              className={clsx(
                'flex items-center justify-center gap-2 py-3 rounded-xl border text-sm font-bold transition-all',
                halted
                  ? 'bg-green/10 border-green/30 text-green animate-pulse'
                  : 'bg-red/10 border-red/20 text-red-l hover:bg-red/15'
              )}
            >
              {halted ? <CheckCircle size={14} /> : <ShieldOff size={14} />}
              {halted ? 'Clear Halt' : 'Emergency Halt'}
            </motion.button>
          </div>

          {/* Action feedback */}
          <AnimatePresence>
            {actionMsg && (
              <motion.div
                initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="text-center text-sm text-amber py-2"
              >
                {actionMsg}
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── TODAY'S TRADES ─────────────────────────────────────── */}
          {trades.length > 0 && (
            <div className="rounded-2xl border border-line/40 bg-card/60 backdrop-blur p-5">
              <div className="text-xs font-black text-text3 uppercase tracking-widest mb-3">Today's Trades</div>
              <div className="flex flex-col gap-2">
                {trades.map((t, i) => (
                  <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-surface border border-line/30">
                    <div className={clsx(
                      'w-8 h-8 rounded-lg flex items-center justify-center text-xs font-black',
                      t.net_pnl > 0 ? 'bg-green/15 text-green' : 'bg-red/15 text-red-l'
                    )}>
                      {t.direction === 'CALL' ? '▲' : '▼'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-text2 truncate">{t.symbol}</div>
                      <div className="text-[10px] text-text3">{t.strategy} · {t.exit_reason}</div>
                    </div>
                    <div className="text-right">
                      <div className={clsx('text-sm font-black font-mono', pnlColor(t.net_pnl))}>
                        {t.net_pnl >= 0 ? '+' : ''}₹{Math.abs(t.net_pnl).toFixed(0)}
                      </div>
                      <div className="text-[10px] text-text3">{t.lots}L · {t.exit_price?.toFixed(0)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT COLUMN ─────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* ── REGIME PANEL ─────────────────────────────────────── */}
          <div className="rounded-2xl border border-line/40 bg-card/60 backdrop-blur p-5">
            <div className="flex items-center gap-2 mb-4">
              <Radio size={13} className="text-accent" />
              <span className="text-xs font-black text-text3 uppercase tracking-widest">Market Regime</span>
            </div>

            {n?.regime ? (
              <>
                <div className="text-2xl font-black text-text1 mb-1">{n.regime}</div>
                <div className="flex items-center gap-2 mb-3">
                  {biasIcon(n.regime_bias)}
                  <span className={clsx('text-sm font-bold', biasColor(n.regime_bias))}>
                    Bias: {n.regime_bias ?? 'NEUTRAL'}
                  </span>
                </div>
                {n.window && (
                  <div className="flex items-center gap-1.5 mb-3">
                    <Clock size={11} className="text-text3" />
                    <span className="text-xs text-text3">Entry window:</span>
                    <span className="text-xs font-mono font-bold text-text2">{n.window}</span>
                  </div>
                )}
                {n.regime_detail && (
                  <p className="text-xs text-text3 leading-relaxed border-t border-line/30 pt-3">
                    {n.regime_detail}
                  </p>
                )}
              </>
            ) : (
              <div className="text-sm text-text3 italic">Classifying regime...</div>
            )}
          </div>

          {/* ── BOT LOGIC EXPLAINER ────────────────────────────────── */}
          <div className="rounded-2xl border border-line/40 bg-card/60 backdrop-blur p-5">
            <div className="flex items-center gap-2 mb-4">
              <Zap size={13} className="text-cyan" />
              <span className="text-xs font-black text-text3 uppercase tracking-widest">How Bot Enters</span>
            </div>
            <div className="flex flex-col gap-2.5 text-xs text-text3">
              {[
                { label: 'Regime', val: 'SKIP if VIX>30 or gap>3%' },
                { label: 'Direction', val: '2/3 candles + above/below VWAP' },
                { label: 'RSI', val: 'Not >78 for CALL, not <22 for PUT' },
                { label: 'Price', val: 'Option LTP must be ₹50–₹450' },
                { label: 'Lots', val: 'Dynamic: risk_budget ÷ ltp × sl% × 65' },
                { label: 'Strike', val: 'ATM (conv<0.85) or OTM1 (conv≥0.85)' },
                { label: 'SL', val: 'Limit order, 15–35% of premium' },
                { label: 'Trail', val: 'BE at +12%, trail at +20%' },
              ].map(({ label, val }) => (
                <div key={label} className="flex items-start gap-2">
                  <ChevronRight size={10} className="text-accent mt-0.5 shrink-0" />
                  <div>
                    <span className="font-bold text-text2">{label}: </span>
                    <span>{val}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── RISK SNAPSHOT ───────────────────────────────────────── */}
          <div className="rounded-2xl border border-line/40 bg-card/60 backdrop-blur p-5">
            <div className="flex items-center gap-2 mb-4">
              <Target size={13} className="text-accent" />
              <span className="text-xs font-black text-text3 uppercase tracking-widest">Risk Snapshot</span>
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex justify-between">
                <span className="text-xs text-text3">Daily P&L</span>
                <span className={clsx('text-xs font-mono font-bold', pnlColor(pnl))}>
                  {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-xs text-text3">Trades taken</span>
                <span className="text-xs font-mono font-bold text-text1">{todayCount}</span>
              </div>
              {halted && (
                <div className="flex items-center gap-1.5 mt-1 p-2 rounded-lg bg-red/10 border border-red/30">
                  <AlertTriangle size={11} className="text-red-l" />
                  <span className="text-xs text-red-l font-bold">HALT ACTIVE</span>
                </div>
              )}
              {paused && !halted && (
                <div className="flex items-center gap-1.5 mt-1 p-2 rounded-lg bg-amber/10 border border-amber/30">
                  <Pause size={11} className="text-amber" />
                  <span className="text-xs text-amber font-bold">BOT PAUSED</span>
                </div>
              )}
            </div>
          </div>

          {/* ── POWER BUTTON ──────────────────────────────────────── */}
          <div className="text-center">
            <div className="text-[10px] text-text3 mb-2">Bot process must be started on server</div>
            <div className="font-mono text-[10px] text-text3 bg-surface rounded-lg p-2 border border-line/30">
              docker restart nifty-bot
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
