import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Play,
  Pause,
  SkipForward,
  SkipBack,
  FastForward,
  Rewind,
  Crosshair,
  BarChart3,
  Clock,
  Loader2,
  AlertCircle,
  Layers,
  Activity,
  Target,
  Shield,
  Radio,
  LogOut,
  TrendingUp,
  Gauge,
} from 'lucide-react'
import { FilterVisualizer } from '../components/panels/FilterVisualizer'

const STEP_COUNT = 6
const BASE_STEP_MS = 2200

const STEP_META = [
  { id: 'regime', label: 'REGIME DETECTED', icon: Radio },
  { id: 'signal', label: 'SIGNAL DETECTED', icon: Activity },
  { id: 'entry', label: 'ENTRY ORDER', icon: Crosshair },
  { id: 'risk', label: 'RISK SET', icon: Shield },
  { id: 'monitor', label: 'POSITION MONITORING', icon: Gauge },
  { id: 'exit', label: 'EXIT', icon: LogOut },
] as const

export interface ReplayTrade {
  direction?: string
  option_type?: string
  strike?: number
  expiry?: string
  entry_ts?: string
  exit_ts?: string
  entry_price?: number
  exit_price?: number
  sl_price?: number
  target_price?: number
  exit_reason?: string
  gross_pnl?: number
  charges?: number
  net_pnl?: number
  qty?: number
  lots?: number
  spot_at_entry?: number
  delta_at_entry?: number
  iv_at_entry?: number
  vix?: number
  trade_date?: string
  entry_slippage_pct?: number
  slippage_pct?: number
  strategy?: string
  regime?: string
  filter_log?: Record<string, unknown>
  symbol?: string
  status?: string
}

function fmtTime(iso?: string) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return '—'
  }
}

function n(v: unknown, digits = 2): string {
  if (v == null || typeof v !== 'number' || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}

function tradeLabel(t: ReplayTrade) {
  return t.symbol ?? `NIFTY ${t.strike ?? '—'} ${t.option_type ?? ''}`
}

function riskMetrics(t: ReplayTrade) {
  const entry = t.entry_price
  const sl = t.sl_price
  const target = t.target_price
  if (entry == null || sl == null || target == null || entry === 0) {
    return { slPct: null as number | null, tgtPct: null as number | null, rr: null as number | null }
  }
  const risk = Math.abs(entry - sl)
  const reward = Math.abs(target - entry)
  const slPct = (risk / entry) * 100
  const tgtPct = (reward / entry) * 100
  const rr = risk > 1e-6 ? reward / risk : null
  return { slPct, tgtPct, rr }
}

function PriceLevelBar({ trade }: { trade: ReplayTrade }) {
  const entry = trade.entry_price
  const sl = trade.sl_price
  const target = trade.target_price
  const exit = trade.exit_price

  const points = [entry, sl, target, exit].filter((x): x is number => typeof x === 'number' && !Number.isNaN(x))
  if (points.length < 2) {
    return (
      <div className="text-[10px] text-text3 text-center py-6 border border-dashed border-line/25 rounded-xl">
        Not enough price data to draw the bar
      </div>
    )
  }

  const minP = Math.min(...points)
  const maxP = Math.max(...points)
  const pad = Math.max((maxP - minP) * 0.08, 0.5)
  const lo = minP - pad
  const hi = maxP + pad
  const span = hi - lo || 1

  const pct = (p: number) => ((p - lo) / span) * 100

  const markers: { key: string; price: number; color: string; label: string }[] = []
  if (entry != null) markers.push({ key: 'entry', price: entry, color: 'bg-accent', label: 'Entry' })
  if (sl != null) markers.push({ key: 'sl', price: sl, color: 'bg-red', label: 'SL' })
  if (target != null) markers.push({ key: 'tgt', price: target, color: 'bg-green', label: 'Target' })
  if (exit != null) markers.push({ key: 'exit', price: exit, color: 'bg-amber', label: 'Exit' })

  return (
    <div className="space-y-3">
      <div className="relative h-14 rounded-xl bg-surface/60 border border-line/20 overflow-hidden">
        <div className="absolute inset-x-3 top-1/2 h-1 -translate-y-1/2 rounded-full bg-line/30" />
        {markers.map((m) => (
          <motion.div
            key={m.key}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center"
            style={{ left: `${pct(m.price)}%` }}
          >
            <div className={clsx('w-3 h-3 rounded-full border-2 border-[#0c1020] shadow-md z-10', m.color)} />
            <span className="mt-5 whitespace-nowrap text-[9px] font-bold text-text3 uppercase tracking-wide">
              {m.label}
            </span>
          </motion.div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 justify-center text-[10px] font-mono text-text2">
        {markers.map((m) => (
          <span key={m.key} className="flex items-center gap-1.5">
            <span className={clsx('w-2 h-2 rounded-full', m.color)} />
            {m.label}: ₹{n(m.price, 2)}
          </span>
        ))}
      </div>
    </div>
  )
}

function StepDetailPanel({ step, trade }: { step: number; trade: ReplayTrade }) {
  const slip = trade.entry_slippage_pct ?? trade.slippage_pct
  const { slPct, tgtPct, rr } = riskMetrics(trade)
  const isCall = (trade.direction ?? '').toUpperCase().includes('CALL') || trade.option_type === 'CE'

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={step}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.22 }}
        className="glass-card rounded-2xl p-5 neon-border min-h-[200px]"
      >
        {step === 0 && (
          <div className="space-y-3">
            <p className="text-[11px] text-text3 leading-relaxed">
              Session classification before any strategy is chosen. Regime drives which playbook is eligible and how
              aggressive filters are.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3 tracking-wider">Regime</div>
                <div className="text-lg font-extrabold text-accent-l mt-1">{trade.regime ?? '—'}</div>
              </div>
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3 tracking-wider">Trade date</div>
                <div className="text-[13px] font-bold text-text1 mt-1 font-mono">{trade.trade_date ?? '—'}</div>
              </div>
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3 tracking-wider">Spot @ context</div>
                <div className="text-[13px] font-bold font-mono text-text1 mt-1">₹{n(trade.spot_at_entry)}</div>
              </div>
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3 tracking-wider">VIX (context)</div>
                <div className="text-[13px] font-bold font-mono text-text1 mt-1">{n(trade.vix, 2)}</div>
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={clsx(
                  'text-[10px] font-bold px-2 py-0.5 rounded-lg',
                  trade.strategy === 'ORB'
                    ? 'bg-amber/10 text-amber'
                    : trade.strategy === 'VWAP'
                      ? 'bg-cyan/10 text-cyan'
                      : 'bg-accent/10 text-accent-l',
                )}
              >
                {trade.strategy ?? '—'}
              </span>
              <span
                className={clsx(
                  'text-[10px] font-bold px-2 py-0.5 rounded-lg',
                  isCall ? 'bg-green/10 text-green' : 'bg-red/10 text-red-l',
                )}
              >
                {trade.direction ?? '—'}
              </span>
              <span className="text-[10px] text-text3 font-mono">{fmtTime(trade.entry_ts)}</span>
            </div>
            <p className="text-[11px] text-text3">
              Strategy signal fired with the following entry filter breakdown. All filters must align with your live
              config for a trade to be taken.
            </p>
            {trade.filter_log && Object.keys(trade.filter_log).length > 0 ? (
              <>
                <div className="neon-border rounded-2xl overflow-hidden">
                  <FilterVisualizer filterLog={trade.filter_log as Record<string, unknown>} />
                </div>
                <div className="space-y-2 max-h-[180px] overflow-y-auto pr-1">
                  {Object.entries(trade.filter_log).map(([key, raw]) => {
                    const v = raw as Record<string, unknown> | boolean | null
                    const detail =
                      v && typeof v === 'object' && typeof v.detail === 'string' ? v.detail : null
                    if (!detail) return null
                    const ok =
                      v === true ||
                      (v !== null && typeof v === 'object' && (v as { passed?: boolean }).passed === true)
                    return (
                      <div
                        key={key}
                        className={clsx(
                          'text-[10px] rounded-lg px-2.5 py-1.5 border',
                          ok ? 'bg-green/5 border-green/15 text-text2' : 'bg-red/5 border-red/20 text-text2',
                        )}
                      >
                        <span className="font-bold capitalize text-text1">{key.replace(/_/g, ' ')}:</span>{' '}
                        <span className="text-text3">{detail}</span>
                      </div>
                    )
                  })}
                </div>
              </>
            ) : (
              <div className="text-[11px] text-text3 italic py-4 text-center border border-dashed border-line/20 rounded-xl">
                No filter log on this trade
              </div>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
              <div className="text-[9px] font-bold uppercase text-text3">Entry price</div>
              <div className="text-xl font-extrabold font-mono text-accent-l mt-1">₹{n(trade.entry_price)}</div>
              <div className="text-[10px] text-text3 mt-1">{fmtTime(trade.entry_ts)}</div>
            </div>
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
              <div className="text-[9px] font-bold uppercase text-text3">Strike · type</div>
              <div className="text-[15px] font-bold text-text1 mt-1 font-mono">
                {n(trade.strike, 0)} {trade.option_type ?? '—'}
              </div>
              <div className="text-[10px] text-text3 mt-1">Exp {trade.expiry ?? '—'}</div>
            </div>
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3 sm:col-span-2">
              <div className="text-[9px] font-bold uppercase text-text3">Slippage (entry)</div>
              <div className="text-[14px] font-bold font-mono text-amber mt-1">
                {slip != null ? `${slip >= 0 ? '+' : ''}${n(slip, 2)}%` : '—'}
              </div>
              <div className="text-[10px] text-text3 mt-1">
                Qty {n(trade.qty, 0)} · Lots {n(trade.lots, 0)}
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="rounded-xl bg-surface/50 border border-red/15 p-3">
                <div className="text-[9px] font-bold uppercase text-red">Stop loss</div>
                <div className="text-lg font-extrabold font-mono text-red-l mt-1">₹{n(trade.sl_price)}</div>
                <div className="text-[10px] text-text3 mt-1">
                  Distance {slPct != null ? `${n(slPct, 2)}%` : '—'} from entry
                </div>
              </div>
              <div className="rounded-xl bg-surface/50 border border-green/15 p-3">
                <div className="text-[9px] font-bold uppercase text-green">Target</div>
                <div className="text-lg font-extrabold font-mono text-green mt-1">₹{n(trade.target_price)}</div>
                <div className="text-[10px] text-text3 mt-1">
                  Distance {tgtPct != null ? `${n(tgtPct, 2)}%` : '—'} from entry
                </div>
              </div>
            </div>
            <div className="rounded-xl bg-accent/8 border border-accent/25 p-4 text-center">
              <div className="text-[9px] font-bold uppercase text-text3 tracking-widest">Risk : reward</div>
              <div className="text-2xl font-black font-mono text-accent-l mt-1">
                {rr != null ? `1 : ${n(rr, 2)}` : '—'}
              </div>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
              <div className="text-[9px] font-bold uppercase text-text3">IV @ entry</div>
              <div className="text-[16px] font-bold font-mono text-cyan mt-1">
                {trade.iv_at_entry != null ? `${n(trade.iv_at_entry * 100, 2)}%` : '—'}
              </div>
              <div className="text-[9px] text-text3 mt-1">Annualized σ</div>
            </div>
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
              <div className="text-[9px] font-bold uppercase text-text3">Delta @ entry</div>
              <div className="text-[16px] font-bold font-mono text-text1 mt-1">{n(trade.delta_at_entry, 4)}</div>
            </div>
            <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
              <div className="text-[9px] font-bold uppercase text-text3">VIX</div>
              <div className="text-[16px] font-bold font-mono text-amber mt-1">{n(trade.vix, 2)}</div>
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3">Exit price</div>
                <div className="text-xl font-extrabold font-mono text-text1 mt-1">₹{n(trade.exit_price)}</div>
                <div className="text-[10px] text-text3 mt-1">{fmtTime(trade.exit_ts)}</div>
              </div>
              <div className="rounded-xl bg-surface/50 border border-line/15 p-3">
                <div className="text-[9px] font-bold uppercase text-text3">Exit reason</div>
                <div className="text-[13px] font-bold text-text1 mt-1">
                  {(trade.exit_reason ?? '—').replace(/_/g, ' ')}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-lg bg-surface/40 border border-line/10 p-2 text-center">
                <div className="text-[8px] font-bold text-text3 uppercase">Gross</div>
                <div
                  className={clsx(
                    'text-[12px] font-bold font-mono',
                    (trade.gross_pnl ?? 0) >= 0 ? 'text-green' : 'text-red',
                  )}
                >
                  ₹{n(trade.gross_pnl)}
                </div>
              </div>
              <div className="rounded-lg bg-surface/40 border border-line/10 p-2 text-center">
                <div className="text-[8px] font-bold text-text3 uppercase">Charges</div>
                <div className="text-[12px] font-bold font-mono text-text2">₹{n(trade.charges)}</div>
              </div>
              <div className="rounded-lg bg-surface/40 border border-line/10 p-2 text-center">
                <div className="text-[8px] font-bold text-text3 uppercase">Net</div>
                <div
                  className={clsx(
                    'text-[12px] font-bold font-mono',
                    (trade.net_pnl ?? 0) >= 0 ? 'text-green-l' : 'text-red-l',
                  )}
                >
                  ₹{n(trade.net_pnl)}
                </div>
              </div>
            </div>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  )
}

export function TradeReplayPage() {
  const [trades, setTrades] = useState<ReplayTrade[]>([])
  const [strategy, setStrategy] = useState('BOTH')
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<1 | 2 | 4>(1)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const trade = trades[selectedIdx]

  const loadTrades = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const r = await axios.post<{ trades?: ReplayTrade[] }>('/api/backtest/run', {
        strategy,
        start_date: startDate,
        end_date: endDate,
      })
      const list = Array.isArray(r.data.trades) ? r.data.trades : []
      setTrades(list)
      setSelectedIdx(0)
      setStep(0)
      setPlaying(false)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Failed to load trades')
      setTrades([])
    } finally {
      setLoading(false)
    }
  }, [strategy, startDate, endDate])

  const pause = useCallback(() => setPlaying(false), [])
  const play = useCallback(() => {
    if (!trade) return
    if (step >= STEP_COUNT - 1) setStep(0)
    setPlaying(true)
  }, [trade, step])

  const stepForward = useCallback(() => {
    setStep((s) => Math.min(STEP_COUNT - 1, s + 1))
  }, [])

  const stepBack = useCallback(() => {
    setStep((s) => Math.max(0, s - 1))
  }, [])

  const resetReplay = useCallback(() => {
    setStep(0)
    setPlaying(false)
  }, [])

  useEffect(() => {
    if (!playing || !trade) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }
    intervalRef.current = setInterval(() => {
      setStep((prev) => {
        if (prev >= STEP_COUNT - 1) {
          setPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, BASE_STEP_MS / speed)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [playing, speed, trade])

  useEffect(() => {
    setStep(0)
    setPlaying(false)
  }, [selectedIdx])

  const isWin = (trade?.net_pnl ?? 0) >= 0

  const summaryPrices = useMemo(() => {
    if (!trade) return []
    return [
      { label: 'Spot', val: trade.spot_at_entry, color: 'text-text2' },
      { label: 'Entry', val: trade.entry_price, color: 'text-accent-l' },
      { label: 'SL', val: trade.sl_price, color: 'text-red' },
      { label: 'Target', val: trade.target_price, color: 'text-green' },
      { label: 'Exit', val: trade.exit_price, color: isWin ? 'text-green-l' : 'text-red-l' },
    ]
  }, [trade, isWin])

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between flex-wrap gap-3"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
            <Play size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-text1 tracking-tight">Trade Replay</h1>
            <p className="text-[11px] text-text3">Step-through playback from backtest trade data (no simulated ticks)</p>
          </div>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-4 space-y-3">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-card rounded-2xl p-4 neon-border"
          >
            <div className="flex items-center gap-2 mb-3">
              <Layers size={13} className="text-accent" />
              <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Load from backtest</span>
            </div>
            <div className="space-y-2.5">
              <div>
                <label className="block text-[9px] font-bold text-text3 uppercase tracking-wider mb-1">Strategy</label>
                <select
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                  className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2 text-[11px] text-text1 focus:border-accent/40 focus:outline-none font-semibold cursor-pointer"
                >
                  <option value="BOTH">ALL — Multi-strategy</option>
                  <option value="ORB">ORB</option>
                  <option value="VWAP">VWAP</option>
                  <option value="MR">MR</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[9px] font-bold text-text3 uppercase mb-1">Start</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full bg-surface border border-line/30 rounded-xl px-2 py-2 text-[10px] text-text1 font-mono focus:border-accent/40 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[9px] font-bold text-text3 uppercase mb-1">End</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full bg-surface border border-line/30 rounded-xl px-2 py-2 text-[10px] text-text1 font-mono focus:border-accent/40 focus:outline-none"
                  />
                </div>
              </div>
              <motion.button
                type="button"
                onClick={loadTrades}
                disabled={loading}
                whileHover={{ scale: loading ? 1 : 1.02 }}
                whileTap={{ scale: 0.98 }}
                className={clsx(
                  'w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-[12px] font-bold border transition-all',
                  loading
                    ? 'bg-accent/10 text-accent border-accent/20 cursor-wait'
                    : 'bg-accent text-white border-accent hover:shadow-lg hover:shadow-accent/20',
                )}
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <BarChart3 size={14} />}
                {loading ? 'Loading…' : 'Load Trades'}
              </motion.button>
            </div>
          </motion.div>

          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="glass-card rounded-xl p-3 border-l-[3px] border-l-red flex items-start gap-2 neon-border"
              >
                <AlertCircle size={14} className="text-red shrink-0 mt-0.5" />
                <span className="text-[11px] text-red-l">{error}</span>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="glass-card rounded-2xl overflow-hidden neon-border">
            <div className="px-4 py-2.5 border-b border-line/20 flex items-center justify-between">
              <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Trades</span>
              <span className="text-[10px] font-mono text-text3">{trades.length}</span>
            </div>
            <div className="max-h-[min(52vh,520px)] overflow-y-auto divide-y divide-line/10">
              {trades.length === 0 && !loading && (
                <div className="px-4 py-10 text-center">
                  <BarChart3 size={22} className="text-text3 mx-auto mb-2 opacity-50" />
                  <p className="text-[11px] text-text1 font-semibold">No trades loaded</p>
                  <p className="text-[10px] text-text3 mt-1">Set range and press Load Trades</p>
                </div>
              )}
              {trades.map((t, i) => (
                <button
                  key={`${t.trade_date}-${t.entry_ts}-${i}`}
                  type="button"
                  onClick={() => setSelectedIdx(i)}
                  className={clsx(
                    'w-full text-left px-4 py-3 transition-colors',
                    selectedIdx === i ? 'bg-accent/10' : 'hover:bg-card/40',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={clsx(
                          'w-1.5 h-6 rounded-full shrink-0',
                          (t.net_pnl ?? 0) >= 0 ? 'bg-green' : 'bg-red',
                        )}
                      />
                      <div className="min-w-0">
                        <div className="text-[11px] font-semibold text-text1 truncate">
                          {t.strategy ?? '—'} · {t.direction ?? '—'}
                        </div>
                        <div className="text-[9px] text-text3 font-mono truncate">
                          {t.trade_date ?? '—'}
                        </div>
                      </div>
                    </div>
                    <span
                      className={clsx(
                        'text-[11px] font-bold font-mono shrink-0',
                        (t.net_pnl ?? 0) >= 0 ? 'text-green' : 'text-red',
                      )}
                    >
                      {(t.net_pnl ?? 0) >= 0 ? '+' : ''}₹{n(t.net_pnl, 0)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="lg:col-span-8 space-y-4">
          {!trade ? (
            <div className="glass-card rounded-2xl p-14 text-center neon-border">
              <TrendingUp size={26} className="text-text3 mx-auto mb-3 opacity-40" />
              <p className="text-text1 font-semibold text-[13px]">Select a trade after loading</p>
              <p className="text-text3 text-[11px] mt-1">Replay uses real fields from the backtest engine</p>
            </div>
          ) : (
            <>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="glass-card rounded-2xl p-5 neon-border"
              >
                <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className={clsx(
                        'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                        (trade.direction ?? '').includes('CALL') || trade.option_type === 'CE'
                          ? 'bg-green/10'
                          : 'bg-red/10',
                      )}
                    >
                      <Crosshair
                        size={18}
                        className={
                          (trade.direction ?? '').includes('CALL') || trade.option_type === 'CE'
                            ? 'text-green'
                            : 'text-red'
                        }
                      />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[13px] font-bold text-text1 flex flex-wrap items-center gap-2">
                        <span className="truncate">{tradeLabel(trade)}</span>
                        <span
                          className={clsx(
                            'text-[9px] font-bold px-1.5 py-0.5 rounded',
                            trade.strategy === 'ORB'
                              ? 'bg-amber/10 text-amber'
                              : 'bg-cyan/10 text-cyan',
                          )}
                        >
                          {trade.strategy}
                        </span>
                        <span
                          className={clsx(
                            'text-[9px] font-bold px-1.5 py-0.5 rounded',
                            (trade.direction ?? '').includes('CALL') || trade.option_type === 'CE'
                              ? 'bg-green/10 text-green'
                              : 'bg-red/10 text-red',
                          )}
                        >
                          {trade.direction}
                        </span>
                      </div>
                      <div className="text-[11px] text-text3 mt-0.5 font-mono">
                        {trade.trade_date} · {fmtTime(trade.entry_ts)} → {fmtTime(trade.exit_ts)}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={clsx('text-xl font-extrabold font-mono stat-val', isWin ? 'text-green-l' : 'text-red-l')}
                    >
                      {isWin ? '+' : ''}₹{n(trade.net_pnl)}
                    </div>
                    <div className="text-[10px] text-text3 mt-0.5">
                      Strike {n(trade.strike, 0)} {trade.option_type} · Exp {trade.expiry ?? '—'}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4">
                  {summaryPrices.map(({ label, val, color }) => (
                    <div key={label} className="bg-surface/50 rounded-xl p-2.5 border border-line/15 text-center">
                      <div className="text-[9px] font-bold uppercase text-text3 mb-0.5">{label}</div>
                      <div className={clsx('text-[12px] font-bold font-mono stat-val', color)}>
                        {val != null ? `₹${n(val)}` : '—'}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mb-4">
                  <div className="text-[10px] font-bold uppercase text-text3 tracking-wider mb-2 flex items-center gap-2">
                    <Target size={11} className="text-accent" />
                    Price map (option premium)
                  </div>
                  <PriceLevelBar trade={trade} />
                </div>

                <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 pt-2 border-t border-line/15">
                  <button
                    type="button"
                    onClick={resetReplay}
                    className="p-2 rounded-lg bg-surface border border-line/20 text-text3 hover:text-text2 transition-colors"
                    title="Reset"
                  >
                    <Rewind size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={stepBack}
                    disabled={step === 0}
                    className="p-2 rounded-lg bg-surface border border-line/20 text-text3 hover:text-text2 transition-colors disabled:opacity-30"
                  >
                    <SkipBack size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={playing ? pause : play}
                    className={clsx(
                      'p-3 rounded-xl border text-white transition-all',
                      playing
                        ? 'bg-amber border-amber'
                        : 'bg-accent border-accent hover:shadow-lg hover:shadow-accent/20',
                    )}
                  >
                    {playing ? <Pause size={16} /> : <Play size={16} />}
                  </button>
                  <button
                    type="button"
                    onClick={stepForward}
                    disabled={step >= STEP_COUNT - 1}
                    className="p-2 rounded-lg bg-surface border border-line/20 text-text3 hover:text-text2 transition-colors disabled:opacity-30"
                  >
                    <SkipForward size={14} />
                  </button>
                  <div className="flex items-center gap-1 px-1">
                    {([1, 2, 4] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setSpeed(s)}
                        className={clsx(
                          'flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-[10px] font-bold transition-colors',
                          speed === s
                            ? 'bg-accent/20 border-accent/40 text-accent-l'
                            : 'bg-surface border-line/20 text-text3 hover:text-text2',
                        )}
                      >
                        <FastForward size={11} />
                        {s}x
                      </button>
                    ))}
                  </div>
                </div>
                <div className="text-center text-[10px] text-text3 mt-3">
                  Step {step + 1} / {STEP_COUNT} · {STEP_META[step]?.label}
                </div>
              </motion.div>

              <StepDetailPanel step={step} trade={trade} />

              <div className="glass-card rounded-2xl p-5 neon-border">
                <div className="flex items-center gap-2 mb-4">
                  <Clock size={13} className="text-accent" />
                  <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Timeline</span>
                </div>
                <div className="relative">
                  <div className="absolute left-[11px] top-6 bottom-6 w-px bg-line/25" />
                  <div className="space-y-1">
                    {STEP_META.map((meta, i) => {
                      const Icon = meta.icon
                      const active = i === step
                      const done = i < step
                      return (
                        <motion.button
                          key={meta.id}
                          type="button"
                          initial={false}
                          animate={{
                            backgroundColor: active ? 'rgba(99, 102, 241, 0.12)' : 'transparent',
                          }}
                          onClick={() => {
                            setStep(i)
                            setPlaying(false)
                          }}
                          className={clsx(
                            'relative w-full flex items-start gap-3 pl-1 pr-2 py-2.5 rounded-xl text-left transition-colors',
                            active ? 'ring-1 ring-accent/35' : 'hover:bg-surface/40',
                          )}
                        >
                          <div
                            className={clsx(
                              'relative z-[1] w-6 h-6 rounded-lg flex items-center justify-center shrink-0 text-[9px] font-bold border',
                              active
                                ? 'bg-accent text-white border-accent'
                                : done
                                  ? 'bg-green/15 text-green border-green/25'
                                  : 'bg-surface text-text3 border-line/25',
                            )}
                          >
                            {done && !active ? '✓' : i + 1}
                          </div>
                          <div className="min-w-0 pt-0.5">
                            <div className="flex items-center gap-2">
                              <Icon size={12} className={active ? 'text-accent' : 'text-text3'} />
                              <span
                                className={clsx(
                                  'text-[11px] font-bold',
                                  active ? 'text-text1' : done ? 'text-text2' : 'text-text3',
                                )}
                              >
                                {meta.label}
                              </span>
                            </div>
                          </div>
                        </motion.button>
                      )
                    })}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
