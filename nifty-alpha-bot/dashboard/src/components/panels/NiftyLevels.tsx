/**
 * NiftyLevels — live Nifty price with OHLC, 5D high/low, EMA8/21, VWAP.
 * Data from /api/nifty/quote and /api/daily-watch.breakout_watch.
 */
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import { TrendingUp, TrendingDown, Minus, Activity, BarChart3, ArrowRight } from 'lucide-react'

interface QuoteData {
  price: number | null
  open?: number | null; high?: number | null; low?: number | null
  prev_close?: number | null; change?: number | null; change_pct?: number | null
  volume?: number | null
  error?: string
}
interface Level { label: string; value: number; color: string; hint?: string }

function Gauge({ price, open, high, low }: { price: number; open?: number | null; high?: number | null; low?: number | null }) {
  if (!high || !low || high === low) return null
  const pct = Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100))
  return (
    <div className="mb-4">
      <div className="flex justify-between text-[9px] font-mono text-text3 mb-1">
        <span>L {low.toFixed(0)}</span>
        <span className="text-text2">Day Range</span>
        <span>H {high.toFixed(0)}</span>
      </div>
      <div className="h-2 rounded-full bg-surface relative">
        <div className="absolute inset-y-0 left-0 right-0 rounded-full overflow-hidden">
          <div className="h-full rounded-full"
            style={{ width: '100%', background: 'linear-gradient(to right, rgba(239,68,68,0.3), rgba(245,158,11,0.2), rgba(34,197,94,0.3))' }} />
        </div>
        <motion.div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-text1 border-2 border-bg"
          animate={{ left: `${pct}%` }}
          transition={{ duration: 0.5 }}
        />
      </div>
      {open && (
        <motion.div
          className="absolute top-0 bottom-0 w-0.5 bg-accent/60"
          style={{ left: `${Math.min(100, Math.max(0, ((open - low) / (high - low)) * 100))}%` }}
        />
      )}
    </div>
  )
}

function LevelRow({ level, price }: { level: Level; price: number }) {
  const diff    = price - level.value
  const diffPct = (diff / level.value) * 100
  const above   = diff > 0
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-line/10 last:border-0">
      <div className={clsx('w-1.5 h-1.5 rounded-full shrink-0', level.color)} />
      <span className="text-[11px] text-text2 w-16 shrink-0">{level.label}</span>
      <span className="font-mono text-[11px] font-bold text-text1 flex-1">
        {level.value.toFixed(0)}
      </span>
      <span className={clsx('text-[10px] font-mono font-bold', above ? 'text-green' : 'text-red-l')}>
        {above ? '+' : ''}{diffPct.toFixed(2)}%
      </span>
      <span className="text-[9px] text-text3 font-mono">
        {above ? '▲' : '▼'} {Math.abs(diff).toFixed(0)}
      </span>
    </div>
  )
}

export function NiftyLevels() {
  const [quote, setQuote] = useState<QuoteData>({ price: null })
  const [levels, setLevels] = useState<Level[]>([])
  const [lastTs, setLastTs] = useState<number>(0)

  // Fetch quote every 15s
  useEffect(() => {
    const fetch = async () => {
      try {
        const r = await axios.get<QuoteData>('/api/nifty/quote')
        if (r.data.price) { setQuote(r.data); setLastTs(Date.now()) }
      } catch {}
    }
    fetch()
    const id = setInterval(fetch, 15_000)
    return () => clearInterval(id)
  }, [])

  // Fetch key levels from daily-watch
  useEffect(() => {
    const fetch = async () => {
      try {
        const r = await axios.get('/api/daily-watch')
        const bw = r.data?.breakout_watch ?? {}
        const newLevels: Level[] = []
        if (bw.prior_5d_high)  newLevels.push({ label: '5D High',  value: bw.prior_5d_high,  color: 'bg-green', hint: 'Breakout trigger' })
        if (bw.prior_5d_low)   newLevels.push({ label: '5D Low',   value: bw.prior_5d_low,   color: 'bg-red-l', hint: 'Bear trigger' })
        if (bw.ema8)           newLevels.push({ label: 'EMA 8',    value: bw.ema8,            color: 'bg-accent', hint: 'Fast trend' })
        if (bw.ema21)          newLevels.push({ label: 'EMA 21',   value: bw.ema21,           color: 'bg-cyan', hint: 'Slow trend' })
        if (bw.vwap)           newLevels.push({ label: 'VWAP',     value: bw.vwap,            color: 'bg-amber', hint: 'Reclaim level' })
        if (bw.last_close)     newLevels.push({ label: 'Prev Close',value: bw.last_close,     color: 'bg-text3', hint: 'Ref' })
        setLevels(newLevels.sort((a, b) => b.value - a.value))
      } catch {}
    }
    fetch()
    const id = setInterval(fetch, 60_000)
    return () => clearInterval(id)
  }, [])

  const price     = quote.price
  const changePct = quote.change_pct ?? (quote.prev_close && price ? ((price - quote.prev_close) / quote.prev_close * 100) : null)
  const up        = changePct != null ? changePct >= 0 : null
  const stale     = lastTs > 0 && (Date.now() - lastTs) > 20_000

  return (
    <div className="glass-card rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <BarChart3 size={13} className="text-accent" />
          </div>
          <span className="label">Nifty 50</span>
        </div>
        {stale && <span className="text-[9px] text-amber">stale</span>}
      </div>

      {/* Big price */}
      {price ? (
        <div className="mb-3">
          <div className="flex items-end gap-2 mb-1">
            <AnimatePresence mode="popLayout">
              <motion.div key={Math.round(price)}
                initial={{ y: -4, opacity: 0.5 }} animate={{ y: 0, opacity: 1 }}
                className="font-mono font-black text-3xl text-text1 stat-val tracking-tight">
                {price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </motion.div>
            </AnimatePresence>
            {up !== null && (
              <div className={clsx('flex items-center gap-1 text-sm font-bold mb-1', up ? 'text-green' : 'text-red-l')}>
                {up ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                <span className="font-mono">{changePct! >= 0 ? '+' : ''}{changePct!.toFixed(2)}%</span>
              </div>
            )}
          </div>
          {/* OHLC row */}
          {(quote.open || quote.high || quote.low) && (
            <div className="flex gap-3 text-[10px] font-mono mb-2">
              {quote.open && <span className="text-text3">O <span className="text-text2 font-bold">{quote.open.toFixed(0)}</span></span>}
              {quote.high && <span className="text-text3">H <span className="text-green font-bold">{quote.high.toFixed(0)}</span></span>}
              {quote.low  && <span className="text-text3">L <span className="text-red-l font-bold">{quote.low.toFixed(0)}</span></span>}
              {quote.prev_close && <span className="text-text3">PC <span className="text-text2 font-bold">{quote.prev_close.toFixed(0)}</span></span>}
            </div>
          )}
          {/* Day range gauge */}
          {quote.high && quote.low && (
            <Gauge price={price} open={quote.open} high={quote.high} low={quote.low} />
          )}
        </div>
      ) : (
        <div className="text-text3 text-sm italic mb-4">
          {quote.error ? 'No live quote (token needed)' : 'Connecting...'}
        </div>
      )}

      {/* Key levels */}
      {levels.length > 0 && price && (
        <div>
          <div className="label mb-2">Key Levels</div>
          <div className="space-y-0">
            {levels.map(l => <LevelRow key={l.label} level={l} price={price} />)}
          </div>
        </div>
      )}

      {levels.length === 0 && !price && (
        <div className="text-[11px] text-text3 text-center py-4">
          Connect Kite for live data
        </div>
      )}
    </div>
  )
}