import { Fragment, useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  Calendar,
  ArrowUpRight,
  ArrowDownRight,
  Trophy,
  Target,
  Flame,
  ChevronDown,
  Loader2,
  RefreshCw,
  AlertCircle,
  Activity,
  Wallet,
  Percent,
  Radio,
  Zap,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'
import type { Trade } from '../stores/tradingStore'
import { FilterVisualizer } from '../components/panels/FilterVisualizer'

const FILTERS = [
  'All',
  'ORB',
  'MOMENTUM_BREAKOUT',
  'EMA_PULLBACK',
  'VWAP_RECLAIM',
  'RELAXED_ORB',
  'MEAN_REVERSION',
  'RANGE_FADE',
  'Wins',
  'Losses',
] as const

type FilterT = (typeof FILTERS)[number]

/** Backtest payloads may include fields not yet on the store `Trade` type */
type BacktestTrade = Trade & {
  regime?: string
  qty?: number
  entry_slippage_pct?: number
  delta_at_entry?: number
  iv_at_entry?: number
}

function formatRs(n: number, decimals = 0): string {
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
}

function normalizeBacktestTrade(raw: Record<string, unknown>): BacktestTrade {
  const strike = Number(raw.strike ?? 0)
  const opt = String(raw.option_type ?? 'CE')
  const sym = raw.symbol != null ? String(raw.symbol) : `NIFTY ${strike} ${opt}`
  return {
    entry_ts: String(raw.entry_ts ?? ''),
    exit_ts: raw.exit_ts != null ? String(raw.exit_ts) : undefined,
    symbol: sym,
    direction: String(raw.direction ?? ''),
    option_type: String(raw.option_type ?? ''),
    strike,
    expiry: String(raw.expiry ?? ''),
    strategy: String(raw.strategy ?? ''),
    lots: Number(raw.lots ?? 0),
    entry_price: Number(raw.entry_price ?? 0),
    exit_price: raw.exit_price != null ? Number(raw.exit_price) : undefined,
    sl_price: Number(raw.sl_price ?? 0),
    target_price: Number(raw.target_price ?? 0),
    exit_reason: raw.exit_reason != null ? String(raw.exit_reason) : undefined,
    gross_pnl: raw.gross_pnl != null ? Number(raw.gross_pnl) : undefined,
    charges: raw.charges != null ? Number(raw.charges) : undefined,
    net_pnl: Number(raw.net_pnl ?? 0),
    spot_at_entry: Number(raw.spot_at_entry ?? 0),
    vix: Number(raw.vix ?? 0),
    trade_date: String(raw.trade_date ?? '').slice(0, 10),
    filter_log:
      raw.filter_log && typeof raw.filter_log === 'object'
        ? (raw.filter_log as Record<string, unknown>)
        : undefined,
    regime: raw.regime != null ? String(raw.regime) : undefined,
    qty: raw.qty != null ? Number(raw.qty) : undefined,
    entry_slippage_pct: raw.entry_slippage_pct != null ? Number(raw.entry_slippage_pct) : undefined,
    delta_at_entry: raw.delta_at_entry != null ? Number(raw.delta_at_entry) : undefined,
    iv_at_entry: raw.iv_at_entry != null ? Number(raw.iv_at_entry) : undefined,
  }
}

function sortTradesChronological(t: BacktestTrade[]): BacktestTrade[] {
  return [...t].sort((a, b) => {
    const da = `${a.trade_date}T${a.entry_ts.includes('T') ? a.entry_ts.split('T')[1] ?? '' : ''}`
    const db = `${b.trade_date}T${b.entry_ts.includes('T') ? b.entry_ts.split('T')[1] ?? '' : ''}`
    return da.localeCompare(db)
  })
}

function coerceFilterLogForVisualizer(log: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...log }
  const r = out.regime
  if (r && typeof r === 'object' && r !== null && 'value' in r) {
    out.regime = { passed: true, value: (r as { value: unknown }).value }
  }
  return out
}

function filterPillState(key: string, v: unknown): 'pass' | 'fail' | 'info' {
  if (key === 'regime' && v && typeof v === 'object' && v !== null && 'value' in v) return 'info'
  if (v === true) return 'pass'
  if (v === false) return 'fail'
  if (v && typeof v === 'object' && 'passed' in v) {
    return (v as { passed: boolean }).passed ? 'pass' : 'fail'
  }
  return 'info'
}

function FilterPills({ filterLog }: { filterLog: Record<string, unknown> }) {
  const entries = Object.entries(filterLog || {})
  if (!entries.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([key, v]) => {
        const state = filterPillState(key, v)
        const label = key.replace(/_/g, ' ')
        let text = label
        if (state === 'info' && v && typeof v === 'object' && v !== null && 'value' in v) {
          text = `${label}: ${String((v as { value: unknown }).value)}`
        } else if (state === 'info' && v != null && typeof v !== 'object') {
          text = `${label}: ${String(v)}`
        } else if (state === 'info') {
          text = label
        } else if (state === 'pass') text = `${label} · pass`
        else if (state === 'fail') text = `${label} · fail`

        return (
          <span
            key={key}
            className={clsx(
              'px-2 py-0.5 rounded-lg text-[9px] font-bold uppercase tracking-wide border',
              state === 'pass' && 'bg-green/10 text-green border-green/25',
              state === 'fail' && 'bg-red/10 text-red-l border-red/25',
              state === 'info' && 'bg-cyan/10 text-cyan border-cyan/20',
            )}
          >
            {text}
          </span>
        )
      })}
    </div>
  )
}

type TabMode = 'live' | 'backtest'

export function TradeHistory() {
  const [tab, setTab] = useState<TabMode>('live')
  const [trades, setTrades] = useState<BacktestTrade[]>([])
  const [liveTrades, setLiveTrades] = useState<BacktestTrade[]>([])
  const [liveLoading, setLiveLoading] = useState(false)
  const [filter, setFilter] = useState<FilterT>('All')
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [startDate, setStartDate] = useState('2023-01-01')
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Fetch live trades on mount + auto-refresh
  const fetchLiveTrades = async () => {
    setLiveLoading(true)
    try {
      const r = await axios.get<{ trades?: Record<string, unknown>[] }>('/api/trades?limit=500')
      const raw = r.data?.trades ?? []
      const normalized = raw.map((t: Record<string, unknown>) => {
        const net = Number(t.net_pnl ?? 0)
        return {
          entry_ts: String(t.entry_ts ?? t.ts ?? ''),
          exit_ts: t.exit_ts != null ? String(t.exit_ts) : undefined,
          symbol: String(t.symbol ?? ''),
          direction: String(t.direction ?? t.signal ?? ''),
          option_type: String(t.option_type ?? ''),
          strike: Number(t.strike ?? 0),
          expiry: String(t.expiry ?? ''),
          strategy: String(t.strategy ?? ''),
          lots: Number(t.lots ?? 1),
          entry_price: Number(t.entry_price ?? t.fill_price ?? 0),
          exit_price: t.exit_price != null ? Number(t.exit_price) : undefined,
          sl_price: Number(t.sl_price ?? t.sl ?? 0),
          target_price: Number(t.target_price ?? t.target ?? 0),
          exit_reason: t.exit_reason != null ? String(t.exit_reason) : undefined,
          gross_pnl: t.gross_pnl != null ? Number(t.gross_pnl) : undefined,
          charges: t.charges != null ? Number(t.charges) : undefined,
          net_pnl: net,
          spot_at_entry: Number(t.spot_at_entry ?? 0),
          vix: Number(t.vix ?? 0),
          trade_date: String(t.trade_date ?? t.entry_ts ?? '').slice(0, 10),
          filter_log: undefined,
          regime: t.regime != null ? String(t.regime) : undefined,
          sl_slippage_pct: t.sl_slippage_pct != null ? Number(t.sl_slippage_pct) : undefined,
          sl_extra_loss: t.sl_extra_loss != null ? Number(t.sl_extra_loss) : undefined,
          entry_latency_ms: t.entry_latency_ms != null ? Number(t.entry_latency_ms) : undefined,
          slippage_pct: t.slippage_pct != null ? Number(t.slippage_pct) : undefined,
        } as BacktestTrade & { sl_slippage_pct?: number; sl_extra_loss?: number; entry_latency_ms?: number; slippage_pct?: number }
      })
      setLiveTrades(normalized.reverse())
    } catch { /* ignore */ }
    finally { setLiveLoading(false) }
  }

  useEffect(() => {
    fetchLiveTrades()
    const id = setInterval(fetchLiveTrades, 15000)
    return () => clearInterval(id)
  }, [])

  const loadBacktestTrades = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await axios.post<{ trades?: Record<string, unknown>[] }>('/api/backtest/run', {
        strategy: 'BOTH',
        start_date: startDate,
        end_date: endDate,
      })
      const raw = r.data?.trades ?? []
      const normalized = raw.map((t) => normalizeBacktestTrade(t))
      setTrades(sortTradesChronological(normalized))
      setExpandedKey(null)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Failed to load backtest trades')
    } finally {
      setLoading(false)
    }
  }

  const activeTrades = tab === 'live' ? liveTrades : trades

  const filtered = useMemo(() => {
    return activeTrades.filter((t) => {
      if (filter === 'Wins') return t.net_pnl >= 0
      if (filter === 'Losses') return t.net_pnl < 0
      if (filter === 'All') return true
      return t.strategy === filter
    })
  }, [activeTrades, filter])

  const stats = useMemo(() => {
    if (!filtered.length) return null
    const totalPnl = filtered.reduce((s, t) => s + t.net_pnl, 0)
    const wins = filtered.filter((t) => t.net_pnl >= 0).length
    const losses = filtered.filter((t) => t.net_pnl < 0).length
    const winPnls = filtered.filter((t) => t.net_pnl >= 0).map((t) => t.net_pnl)
    const lossPnls = filtered.filter((t) => t.net_pnl < 0).map((t) => t.net_pnl)
    const sumWin = winPnls.reduce((a, b) => a + b, 0)
    const sumLossAbs = Math.abs(lossPnls.reduce((a, b) => a + b, 0))
    const best = Math.max(...filtered.map((t) => t.net_pnl))
    const worst = Math.min(...filtered.map((t) => t.net_pnl))
    const avgWin = wins > 0 ? sumWin / wins : 0
    const avgLoss = losses > 0 ? lossPnls.reduce((a, b) => a + b, 0) / losses : 0
    const pf = sumLossAbs > 0 ? sumWin / sumLossAbs : sumWin > 0 ? Infinity : 0
    return {
      totalPnl,
      wins,
      losses,
      best,
      worst,
      avgWin,
      avgLoss,
      pf,
      winRate: filtered.length ? (wins / filtered.length) * 100 : 0,
      count: filtered.length,
    }
  }, [filtered])

  const equityCurve = useMemo(() => {
    let sum = 0
    return filtered.map((t, i) => {
      sum += t.net_pnl
      return {
        x: i + 1,
        pnl: sum,
        date: t.trade_date,
      }
    })
  }, [filtered])

  const dailyBreakdown = useMemo(() => {
    const map = new Map<string, { date: string; pnl: number; count: number; wins: number }>()
    filtered.forEach((t) => {
      const d = map.get(t.trade_date) || { date: t.trade_date, pnl: 0, count: 0, wins: 0 }
      d.pnl += t.net_pnl
      d.count++
      if (t.net_pnl >= 0) d.wins++
      map.set(t.trade_date, d)
    })
    return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date))
  }, [filtered])

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">
      {/* Header + Tab Switcher */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between flex-wrap gap-3"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
            <BarChart3 size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-text1 tracking-tight">Trade History</h1>
            <p className="text-[11px] text-text3">
              {tab === 'live'
                ? (liveTrades.length ? `${liveTrades.length} live trades` : 'No live trades yet — bot not running or no trades today')
                : (trades.length ? `${trades.length} backtest trades loaded` : 'Load trades from the backtest engine')}
            </p>
          </div>
        </div>

        {/* Tab buttons */}
        <div className="flex items-center gap-1 bg-surface/90 rounded-2xl p-1 border border-line/25">
          <button onClick={() => setTab('live')}
            className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold transition-all',
              tab === 'live' ? 'bg-card border border-green/25 text-green' : 'text-text3 hover:text-text2')}>
            <Radio size={12} />
            Live Trades
            {liveTrades.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-green/15 text-green">{liveTrades.length}</span>
            )}
          </button>
          <button onClick={() => setTab('backtest')}
            className={clsx('flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold transition-all',
              tab === 'backtest' ? 'bg-card border border-accent/25 text-accent-l' : 'text-text3 hover:text-text2')}>
            <Zap size={12} />
            Backtest
          </button>
        </div>
      </motion.div>

      {/* Live trades controls */}
      {tab === 'live' && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="glass-card rounded-2xl p-5 neon-border">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="text-[11px] text-text3">
              {liveTrades.length === 0
                ? 'No live trades recorded yet. Trades will appear here once the bot executes orders.'
                : `Showing ${liveTrades.length} trades from live/paper trading sessions. Auto-refreshes every 15s.`}
            </div>
            <motion.button type="button" onClick={fetchLiveTrades} disabled={liveLoading}
              whileHover={{ scale: liveLoading ? 1 : 1.02 }} whileTap={{ scale: 0.98 }}
              className={clsx('flex items-center gap-2 px-4 py-2 rounded-xl text-[12px] font-bold border transition-all',
                liveLoading ? 'bg-green/10 text-green border-green/20 cursor-wait' : 'bg-green/15 text-green border-green/25 hover:bg-green/20')}>
              {liveLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Refresh
            </motion.button>
          </div>
        </motion.div>
      )}

      {/* Backtest load panel */}
      {tab === 'backtest' && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass-card rounded-2xl p-5 neon-border"
        >
          <div className="flex flex-col lg:flex-row lg:items-end gap-3 flex-wrap">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1 min-w-0">
              <div>
                <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">
                  Start date
                </label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none transition-colors"
                />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">
                  End date
                </label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none transition-colors"
                />
              </div>
            </div>
            <motion.button
              type="button"
              onClick={loadBacktestTrades}
              disabled={loading}
              whileHover={{ scale: loading ? 1 : 1.02 }}
              whileTap={{ scale: 0.98 }}
              className={clsx(
                'flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-[12px] font-bold transition-all border shrink-0',
                loading
                  ? 'bg-accent/10 text-accent-l border-accent/20 cursor-wait'
                  : 'bg-accent text-white border-accent hover:shadow-lg hover:shadow-accent/20',
              )}
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {loading ? 'Loading…' : 'Load Backtest Trades'}
            </motion.button>
          </div>
        </motion.div>
      )}

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="glass-card rounded-2xl p-4 border-l-[3px] border-l-red flex items-center gap-3"
          >
            <AlertCircle size={16} className="text-red shrink-0" />
            <span className="text-[12px] text-red-l">{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Strategy filters */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-wrap items-center gap-2"
      >
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={clsx(
              'px-3 py-1.5 rounded-xl text-[11px] font-semibold border transition-all',
              filter === f
                ? 'bg-accent/12 border-accent/25 text-accent-l'
                : 'bg-surface/50 border-line/20 text-text3 hover:text-text2 hover:border-line/40',
            )}
          >
            {f.replace(/_/g, ' ')}
          </button>
        ))}
      </motion.div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 xl:grid-cols-10 gap-3">
          {[
            {
              label: 'Total P&L',
              value: stats.totalPnl,
              prefix: stats.totalPnl >= 0 ? '+₹' : '-₹',
              abs: true,
              color: stats.totalPnl >= 0 ? 'green' : 'red',
              icon: stats.totalPnl >= 0 ? TrendingUp : TrendingDown,
            },
            { label: 'Trades', value: stats.count, color: 'accent', icon: BarChart3 },
            {
              label: 'Win Rate',
              value: stats.winRate,
              suffix: '%',
              decimals: 1,
              color: stats.winRate >= 50 ? 'green' : 'red',
              icon: Percent,
            },
            { label: 'Wins', value: stats.wins, color: 'green', icon: Trophy },
            { label: 'Losses', value: stats.losses, color: 'red', icon: Flame },
            { label: 'Best', value: stats.best, prefix: '₹', color: 'green', icon: ArrowUpRight },
            { label: 'Worst', value: stats.worst, prefix: '₹', color: 'red', icon: ArrowDownRight },
            {
              label: 'Profit Factor',
              value: stats.pf === Infinity ? 99.99 : stats.pf,
              decimals: 2,
              color: stats.pf >= 1 ? 'green' : 'red',
              icon: Target,
            },
            { label: 'Avg Win', value: stats.avgWin, prefix: '₹', decimals: 0, color: 'green', icon: Wallet },
            {
              label: 'Avg Loss',
              value: stats.avgLoss,
              prefix: '₹',
              decimals: 0,
              color: 'red',
              icon: Activity,
            },
          ].map(({ label, value, prefix, suffix, decimals, abs, color, icon: Icon }) => {
            const borderMap = { green: 'border-l-green', red: 'border-l-red', accent: 'border-l-accent' } as const
            const textMap = { green: 'text-green', red: 'text-red', accent: 'text-accent' } as const
            const valTextMap = { green: 'text-green-l', red: 'text-red-l', accent: 'text-accent-l' } as const
            return (
              <motion.div
                key={label}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className={clsx(
                  'glass-card rounded-xl p-3 border-l-[2px] neon-border',
                  borderMap[color as keyof typeof borderMap],
                )}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[9px] font-bold tracking-[0.15em] uppercase text-text3">{label}</span>
                  <Icon size={11} className={textMap[color as keyof typeof textMap]} />
                </div>
                <div
                  className={clsx(
                    'text-[15px] font-extrabold font-mono stat-val',
                    valTextMap[color as keyof typeof valTextMap],
                  )}
                >
                  <CountUp
                    end={abs ? Math.abs(value) : value}
                    prefix={prefix ?? ''}
                    suffix={suffix ?? ''}
                    duration={0.8}
                    decimals={decimals ?? 0}
                    separator=","
                    preserveValue
                  />
                </div>
              </motion.div>
            )
          })}
        </div>
      )}

      {/* Equity curve */}
      {equityCurve.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="glass-card rounded-2xl p-5 neon-border"
        >
          <div className="flex items-center gap-2 mb-3">
            <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
              <TrendingUp size={13} className="text-accent" />
            </div>
            <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">
              Cumulative equity (filtered)
            </span>
          </div>
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={equityCurve}>
                <defs>
                  <linearGradient id="thEqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.2} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1c2244" />
                <XAxis dataKey="x" tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fill: '#4b5c82', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  contentStyle={{
                    background: '#111631',
                    border: '1px solid #1c2244',
                    borderRadius: '10px',
                    fontSize: 11,
                  }}
                  formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'Equity']}
                  labelFormatter={(_, payload) =>
                    payload?.[0]?.payload?.date ? String(payload[0].payload.date) : ''
                  }
                />
                <Area
                  type="monotone"
                  dataKey="pnl"
                  stroke="#6366f1"
                  strokeWidth={2}
                  fill="url(#thEqGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      )}

      {/* Performance heatmap */}
      {dailyBreakdown.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="glass-card rounded-2xl p-5 neon-border"
        >
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
              <Calendar size={13} className="text-cyan" />
            </div>
            <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Performance heatmap</span>
            <span className="ml-auto flex items-center gap-3 text-[9px] text-text3 flex-wrap">
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded bg-red/40" /> Loss
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded bg-surface" /> No trade
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded bg-green/40" /> Profit
              </span>
            </span>
          </div>
          <div className="space-y-4">
            {(() => {
              const months = new Map<string, typeof dailyBreakdown>()
              dailyBreakdown.forEach((d) => {
                const m = d.date.slice(0, 7)
                if (!months.has(m)) months.set(m, [])
                months.get(m)!.push(d)
              })
              const sortedMonths = Array.from(months.entries()).sort(([a], [b]) => a.localeCompare(b))
              return sortedMonths.map(([month, days]) => {
                const firstDay = new Date(month + '-01')
                const daysInMonth = new Date(firstDay.getFullYear(), firstDay.getMonth() + 1, 0).getDate()
                const startDow = firstDay.getDay()
                const allDays: (typeof dailyBreakdown[0] | null)[] = []
                for (let pad = 0; pad < startDow; pad++) allDays.push(null)
                for (let d = 1; d <= daysInMonth; d++) {
                  const dateStr = `${month}-${d.toString().padStart(2, '0')}`
                  const data = days.find((x) => x.date === dateStr)
                  allDays.push(data ?? null)
                }
                return (
                  <div key={month}>
                    <div className="text-[10px] font-bold text-text2 mb-2">
                      {new Date(month + '-01').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}
                    </div>
                    <div className="grid grid-cols-7 gap-1">
                      {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
                        <div key={i} className="text-[8px] font-bold text-text3 text-center py-0.5">
                          {d}
                        </div>
                      ))}
                      {allDays.map((day, i) => {
                        if (day === null && i < startDow) return <div key={`pad-${i}`} />
                        if (!day) {
                          const dayNum = i - startDow + 1
                          if (dayNum < 1 || dayNum > daysInMonth) return <div key={`e-${i}`} />
                          return (
                            <div
                              key={`empty-${i}`}
                              className="aspect-square rounded-lg bg-surface/30 border border-line/10 flex items-center justify-center"
                            >
                              <span className="text-[8px] text-text3/30">{dayNum}</span>
                            </div>
                          )
                        }
                        const intensity = Math.min(1, Math.abs(day.pnl) / 3000)
                        const opacity = 0.15 + intensity * 0.55
                        return (
                          <motion.div
                            key={day.date}
                            initial={{ scale: 0.8 }}
                            animate={{ scale: 1 }}
                            className={clsx(
                              'aspect-square rounded-lg border flex flex-col items-center justify-center cursor-pointer transition-all hover:scale-110 group relative',
                              day.pnl >= 0
                                ? 'border-green/20 hover:border-green/40'
                                : 'border-red/20 hover:border-red/40',
                            )}
                            style={{
                              background:
                                day.pnl >= 0
                                  ? `rgba(16,185,129,${opacity})`
                                  : `rgba(239,68,68,${opacity})`,
                            }}
                          >
                            <span className="text-[8px] font-mono text-text3/70">
                              {parseInt(day.date.slice(8), 10)}
                            </span>
                            <span
                              className={clsx(
                                'text-[8px] font-bold font-mono',
                                day.pnl >= 0 ? 'text-green-l' : 'text-red-l',
                              )}
                            >
                              {day.pnl >= 0 ? '+' : ''}
                              {(day.pnl / 1000).toFixed(1)}k
                            </span>
                            <div className="absolute bottom-full mb-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-20">
                              <div className="bg-panel border border-line/30 rounded-lg px-2.5 py-1.5 text-[9px] whitespace-nowrap shadow-lg">
                                <div className="font-bold text-text1">{day.date}</div>
                                <div className={day.pnl >= 0 ? 'text-green' : 'text-red'}>
                                  P&L: {formatRs(day.pnl)}
                                </div>
                                <div className="text-text3">
                                  {day.count} trades · {day.wins}W
                                </div>
                              </div>
                            </div>
                          </motion.div>
                        )
                      })}
                    </div>
                  </div>
                )
              })
            })()}
          </div>
        </motion.div>
      )}

      {/* Trade table */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass-card rounded-2xl overflow-hidden neon-border"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-line/20">
          <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">{tab === 'live' ? 'Live trades' : 'Backtest trades'}</span>
          <span className="text-[10px] font-bold text-text3">{filtered.length} rows</span>
        </div>
        {filtered.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px] min-w-[1200px]">
              <thead>
                <tr className="border-b border-line/15">
                  {[
                    'Date',
                    'Strategy',
                    'Regime',
                    'Direction',
                    'Entry',
                    'Exit',
                    'SL',
                    'Target',
                    'Slip %',
                    'IV',
                    'VIX',
                    'Charges',
                    'Gross P&L',
                    'Net P&L',
                    'Exit reason',
                    '',
                  ].map((h) => (
                    <th
                      key={h}
                      className="text-left py-2.5 px-3 text-[10px] font-bold tracking-wider text-text3 uppercase whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => {
                  const isUp = t.net_pnl >= 0
                  const rowKey = `${t.trade_date}-${t.entry_ts}-${i}`
                  const isExp = expandedKey === rowKey
                  const iv = t.iv_at_entry
                  const ivPct =
                    iv != null ? (iv <= 1.5 ? iv * 100 : iv) : null
                  const slip = t.entry_slippage_pct
                  const gross = t.gross_pnl ?? t.net_pnl + (t.charges ?? 0)
                  const ch = t.charges ?? 0

                  return (
                    <Fragment key={rowKey}>
                      <tr
                        onClick={() => setExpandedKey(isExp ? null : rowKey)}
                        className={clsx(
                          'border-b border-line/10 hover:bg-card/40 transition-colors cursor-pointer',
                          isExp && 'bg-card/50',
                        )}
                      >
                        <td className="py-2.5 px-3 font-mono text-text3 text-[11px] whitespace-nowrap">
                          {t.trade_date}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={clsx(
                              'px-1.5 py-0.5 rounded text-[10px] font-bold',
                              t.strategy === 'ORB' && 'bg-amber/10 text-amber',
                              t.strategy === 'VWAP_RECLAIM' && 'bg-cyan/10 text-cyan',
                              t.strategy === 'MEAN_REVERSION' && 'bg-accent/10 text-accent-l',
                              t.strategy === 'EMA_PULLBACK' && 'bg-green/10 text-green',
                              t.strategy === 'MOMENTUM_BREAKOUT' && 'bg-green/15 text-green border border-green/20',
                              t.strategy === 'RELAXED_ORB' && 'bg-amber/8 text-amber border border-amber/15',
                              t.strategy === 'RANGE_FADE' && 'bg-cyan/8 text-cyan border border-cyan/15',
                              !['ORB', 'VWAP_RECLAIM', 'MEAN_REVERSION', 'EMA_PULLBACK', 'MOMENTUM_BREAKOUT', 'RELAXED_ORB', 'RANGE_FADE'].includes(
                                t.strategy,
                              ) && 'bg-surface text-text2',
                            )}
                          >
                            {t.strategy.replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-[11px] text-text2">{t.regime ?? '—'}</td>
                        <td className="py-2.5 px-3">
                          <span
                            className={clsx(
                              'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold',
                              t.direction === 'CALL'
                                ? 'bg-green/10 text-green'
                                : 'bg-red/10 text-red',
                            )}
                          >
                            {t.direction === 'CALL' ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
                            {t.direction}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text2 text-[11px] whitespace-nowrap">
                          {formatRs(t.entry_price, 1)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text2 text-[11px] whitespace-nowrap">
                          {t.exit_price != null ? formatRs(t.exit_price, 1) : '—'}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text3 text-[11px] whitespace-nowrap">
                          {formatRs(t.sl_price, 1)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text3 text-[11px] whitespace-nowrap">
                          {formatRs(t.target_price, 1)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text2 text-[11px]">
                          {slip != null ? `${slip.toFixed(2)}%` : '—'}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text2 text-[11px]">
                          {ivPct != null ? `${ivPct.toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text2 text-[11px]">
                          {t.vix.toFixed(1)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-text3 text-[11px]">
                          {formatRs(ch, 0)}
                        </td>
                        <td
                          className={clsx(
                            'py-2.5 px-3 text-right font-mono font-semibold text-[11px]',
                            gross >= 0 ? 'text-green-l' : 'text-red-l',
                          )}
                        >
                          {gross >= 0 ? '+' : ''}
                          {formatRs(gross, 0)}
                        </td>
                        <td
                          className={clsx(
                            'py-2.5 px-3 text-right font-mono font-bold text-[12px]',
                            isUp ? 'text-green' : 'text-red',
                          )}
                        >
                          {isUp ? '+' : ''}
                          {formatRs(t.net_pnl, 0)}
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={clsx(
                              'px-1.5 py-0.5 rounded text-[10px] font-bold',
                              t.exit_reason === 'TARGET_HIT' && 'bg-green/10 text-green',
                              t.exit_reason === 'SL_HIT' && 'bg-red/10 text-red',
                              t.exit_reason === 'FORCE_EXIT' && 'bg-amber/10 text-amber',
                              !t.exit_reason ||
                                !['TARGET_HIT', 'SL_HIT', 'FORCE_EXIT'].includes(t.exit_reason)
                                ? 'bg-surface text-text3'
                                : '',
                            )}
                          >
                            {(t.exit_reason ?? '—').replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td className="py-2.5 px-2">
                          <ChevronDown
                            size={12}
                            className={clsx('text-text3 transition-transform', isExp && 'rotate-180')}
                          />
                        </td>
                      </tr>
                      {isExp && (
                        <tr>
                          <td colSpan={16} className="px-4 py-4 bg-surface/25 border-b border-line/10">
                            <div className="space-y-4">
                              {t.filter_log && Object.keys(t.filter_log).length > 0 && (
                                <div className="space-y-2">
                                  <div className="text-[10px] font-bold uppercase tracking-wider text-text3">
                                    Filter snapshot
                                  </div>
                                  <FilterPills filterLog={t.filter_log as Record<string, unknown>} />
                                  <FilterVisualizer
                                    filterLog={coerceFilterLogForVisualizer(
                                      t.filter_log as Record<string, unknown>,
                                    )}
                                  />
                                </div>
                              )}
                              <div>
                                <div className="text-[10px] font-bold uppercase tracking-wider text-text3 mb-2">
                                  Execution details
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                                  {[
                                    ['Entry slippage', slip != null ? `${slip.toFixed(2)}%` : '—'],
                                    ['Charges', formatRs(ch, 0)],
                                    ['Delta (entry)', t.delta_at_entry != null ? String(t.delta_at_entry) : '—'],
                                    ['IV (entry)', ivPct != null ? `${ivPct.toFixed(2)}%` : '—'],
                                    ['Qty', t.qty != null ? String(t.qty) : '—'],
                                    ['Lots', String(t.lots)],
                                    ['Strike', String(t.strike)],
                                    ['Option', `${t.option_type} · ${t.expiry.slice(0, 10)}`],
                                    ['Spot @ entry', formatRs(t.spot_at_entry, 1)],
                                    ['Symbol', t.symbol],
                                  ].map(([k, v]) => (
                                    <div
                                      key={k}
                                      className="rounded-xl border border-line/15 bg-card/30 px-3 py-2"
                                    >
                                      <div className="text-[9px] font-bold uppercase text-text3">{k}</div>
                                      <div className="text-[11px] font-mono text-text1 mt-0.5">{v}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center">
            <BarChart3 size={18} className="text-text3 mx-auto mb-2" />
            <p className="text-text2 font-medium">No trades to show</p>
            <p className="text-text3 text-[11px] mt-1">
              {tab === 'live'
                ? 'No live trades recorded yet. Trades will appear once the bot executes orders.'
                : 'Set a date range and click "Load Backtest Trades", or widen your filters'}
            </p>
          </div>
        )}
      </motion.div>
    </div>
  )
}
