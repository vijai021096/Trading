/**
 * TopBar — main navigation + live market data ribbon.
 * Shows: logo, nav, Nifty price, VIX, IST clock, bot state, P&L, stop button.
 */
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import {
  Activity, BarChart2, FlaskConical, Settings, AlertTriangle, WifiOff,
  ScrollText, Play, BookOpen, Radar, TrendingUp, TrendingDown, Minus,
  Zap, Shield
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'
import axios from 'axios'

type Page = 'dashboard' | 'trades' | 'backtest' | 'watch' | 'logs' | 'replay' | 'journal' | 'settings'

const NAV: { id: Page; label: string; icon: typeof Activity }[] = [
  { id: 'dashboard', label: 'Live',     icon: Activity },
  { id: 'watch',     label: 'Setup',    icon: Radar },
  { id: 'trades',    label: 'Trades',   icon: BarChart2 },
  { id: 'backtest',  label: 'Backtest', icon: FlaskConical },
  { id: 'logs',      label: 'Logs',     icon: ScrollText },
  { id: 'replay',    label: 'Replay',   icon: Play },
  { id: 'journal',   label: 'Journal',  icon: BookOpen },
  { id: 'settings',  label: 'Settings', icon: Settings },
]

function MarketChip({ label, value, up, small }: { label: string; value: string; up?: boolean | null; small?: boolean }) {
  return (
    <div className={clsx(
      'hidden xl:flex flex-col items-end px-3 py-1 rounded-lg border',
      'bg-card/60 border-line/40'
    )}>
      <div className="text-[9px] font-bold uppercase tracking-widest text-text3">{label}</div>
      <div className={clsx(
        'font-mono font-black leading-tight stat-val',
        small ? 'text-xs' : 'text-sm',
        up === true ? 'text-green' : up === false ? 'text-red-l' : 'text-text1'
      )}>{value}</div>
    </div>
  )
}

export function TopBar({ currentPage, onNavigate }: { currentPage: Page; onNavigate: (p: Page) => void }) {
  const { connected, dailyPnl, emergencyStop, setEmergencyStop, botStatus, runtimeOverride } = useTradingStore()
  const [clock, setClock]   = useState('')
  const [nifty, setNifty]   = useState<{ price: number | null; change_pct: number | null }>({ price: null, change_pct: null })

  // IST clock
  useEffect(() => {
    const tick = () => setClock(
      new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
    )
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  // Nifty quote poll
  useEffect(() => {
    const fetch = async () => {
      try {
        const r = await axios.get('/api/nifty/quote')
        if (r.data.price) setNifty({ price: r.data.price, change_pct: r.data.change_pct ?? null })
      } catch {}
    }
    // fallback from botStatus
    if (botStatus?.nifty_price) setNifty({ price: botStatus.nifty_price, change_pct: botStatus.move_from_open_pct ?? null })
    fetch()
    const id = setInterval(fetch, 15_000)
    return () => clearInterval(id)
  }, [botStatus?.nifty_price])

  const pnl     = dailyPnl?.net_pnl ?? botStatus?.daily_pnl ?? 0
  const pnlPos  = pnl >= 0
  const state   = botStatus?.state ?? 'IDLE'
  const isHalted= botStatus?.halt_active ?? emergencyStop
  const isPaused= botStatus?.paused ?? false
  const vix     = botStatus?.regime_vix ?? null
  const niftyUp = nifty.change_pct != null ? nifty.change_pct > 0 : null

  const stateLabel = isHalted ? 'HALTED' : isPaused ? 'PAUSED' : state
  const stateColor = isHalted
    ? 'bg-red/15 border-red/30 text-red'
    : isPaused
      ? 'bg-amber/15 border-amber/30 text-amber'
      : state === 'ACTIVE'
        ? 'bg-green/15 border-green/30 text-green'
        : 'bg-surface border-line/40 text-text3'

  const handleStop = async () => {
    if (!emergencyStop) {
      if (!confirm('EMERGENCY STOP — halt all trading?')) return
      await axios.post('/api/emergency-stop')
      setEmergencyStop(true)
    } else {
      await axios.delete('/api/emergency-stop')
      setEmergencyStop(false)
    }
  }

  return (
    <header className="sticky top-0 z-50 glass border-b border-line/40">
      {/* Amber scan line */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent" />

      <div className="flex items-center h-[52px] px-4 lg:px-6 gap-3 max-w-[1800px] mx-auto">

        {/* Logo */}
        <div className="flex items-center gap-2.5 shrink-0 mr-2">
          <motion.div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #f59e0b, #d97706)' }}
            whileHover={{ scale: 1.1, rotate: -5 }} whileTap={{ scale: 0.9 }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <polyline points="1,13 5,7 9,10 15,3" stroke="#050810" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="15" cy="3" r="1.8" fill="#050810"/>
            </svg>
          </motion.div>
          <div className="hidden sm:block">
            <div className="text-sm font-black tracking-tight text-gradient leading-none">NIFTY α</div>
            <div className="text-[9px] font-bold tracking-[0.25em] text-text3 uppercase">terminal</div>
          </div>
        </div>

        {/* Nav pills */}
        <nav className="flex items-center gap-0.5 bg-surface/70 rounded-xl p-0.5 border border-line/30 overflow-x-auto shrink-0">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => onNavigate(id)}
              className={clsx(
                'relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold transition-all whitespace-nowrap',
                currentPage === id ? 'text-bg' : 'text-text3 hover:text-text2'
              )}
            >
              {currentPage === id && (
                <motion.div layoutId="nav-pill"
                  className="absolute inset-0 rounded-lg bg-accent"
                  transition={{ type: 'spring', stiffness: 500, damping: 35 }} />
              )}
              <span className="relative z-10 flex items-center gap-1.5">
                <Icon size={12} />
                <span className="hidden lg:inline">{label}</span>
              </span>
            </button>
          ))}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Market data chips */}
        {nifty.price && (
          <div className="hidden xl:flex items-center gap-1 px-3 py-1 rounded-lg border bg-card/60 border-line/40">
            <div className="text-[9px] font-bold uppercase tracking-widest text-text3 mr-1">NIFTY</div>
            <AnimatePresence mode="popLayout">
              <motion.span key={Math.round(nifty.price)}
                initial={{ opacity: 0.5, y: -3 }} animate={{ opacity: 1, y: 0 }}
                className="font-mono font-black text-sm text-text1 stat-val">
                {nifty.price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </motion.span>
            </AnimatePresence>
            {nifty.change_pct != null && (
              <span className={clsx('ml-1 font-mono text-xs font-bold', niftyUp ? 'text-green' : 'text-red-l')}>
                {niftyUp ? <TrendingUp size={10} className="inline mr-0.5" /> : <TrendingDown size={10} className="inline mr-0.5" />}
                {nifty.change_pct >= 0 ? '+' : ''}{nifty.change_pct.toFixed(2)}%
              </span>
            )}
          </div>
        )}

        {vix != null && (() => {
          const vixMax  = runtimeOverride.vix_max ?? 18
          const blocked = vix > vixMax
          return (
            <div className={clsx(
              'hidden xl:flex flex-col items-end px-3 py-1 rounded-lg border',
              blocked ? 'bg-red/10 border-red/30 animate-pulse' : 'bg-card/60 border-line/40'
            )}>
              <div className={clsx('text-[9px] font-bold uppercase tracking-widest', blocked ? 'text-red' : 'text-text3')}>
                {blocked ? '⚠ VIX BLOCK' : 'VIX'}
              </div>
              <div className={clsx('font-mono font-black text-xs stat-val',
                vix < 15 ? 'text-green' : vix > 20 ? 'text-red-l' : 'text-amber')}>
                {Number(vix).toFixed(1)}{blocked ? ` / ${vixMax}` : ''}
              </div>
            </div>
          )
        })()}

        {/* IST Clock */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-line/30 bg-card/50">
          <div className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse-slow" />
          <span className="font-mono text-xs text-text2 stat-val">{clock} IST</span>
        </div>

        {/* Bot state badge */}
        <div className={clsx(
          'hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[10px] font-black uppercase tracking-widest',
          stateColor,
          (isHalted || isPaused) && 'animate-pulse'
        )}>
          {state === 'ACTIVE' && <span className="w-1.5 h-1.5 rounded-full bg-green animate-ping" />}
          {stateLabel}
        </div>

        {/* P&L badge */}
        <AnimatePresence mode="popLayout">
          <motion.div key={Math.round(pnl)}
            initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className={clsx(
              'hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-sm font-black font-mono stat-val',
              pnlPos ? 'bg-green/10 border-green/20 text-green' : 'bg-red/10 border-red/20 text-red-l'
            )}
          >
            <span className="text-[9px] font-sans font-bold text-text3 tracking-wider">P&L</span>
            {pnlPos ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
          </motion.div>
        </AnimatePresence>

        {/* Connection dot */}
        <div className={clsx('flex items-center', connected ? 'text-green' : 'text-red')}>
          {connected ? (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-50"/>
              <span className="relative rounded-full h-2 w-2 bg-green"/>
            </span>
          ) : <WifiOff size={13} />}
        </div>

        {/* Emergency stop */}
        <motion.button onClick={handleStop}
          whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.93 }}
          className={clsx(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-black border transition-all',
            emergencyStop || isHalted
              ? 'bg-green/15 text-green border-green/30 animate-pulse'
              : 'bg-red/10 text-red-l border-red/20 hover:bg-red/15'
          )}
        >
          {emergencyStop || isHalted ? <Shield size={12} /> : <AlertTriangle size={12} />}
          <span className="hidden sm:inline">{emergencyStop || isHalted ? 'CLR' : 'STOP'}</span>
        </motion.button>

      </div>
    </header>
  )
}