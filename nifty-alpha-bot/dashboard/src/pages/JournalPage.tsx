import { useMemo, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  BookOpen,
  ArrowUpRight,
  ArrowDownRight,
  Target,
  Crosshair,
  Clock,
  BarChart3,
  ChevronDown,
  Trophy,
  Flame,
  TrendingUp,
  TrendingDown,
  Calendar,
  Zap,
  CheckCircle2,
  XCircle,
  Loader2,
  Download,
  AlertCircle,
  Sparkles,
  Gauge,
  Layers,
  Info,
} from 'lucide-react'
/** Trade row returned from POST /api/backtest/run */
export interface JournalTrade {
  direction: string
  option_type: string
  strike: number
  expiry: string
  entry_ts: string
  exit_ts?: string
  entry_price: number
  exit_price?: number
  sl_price: number
  target_price: number
  exit_reason?: string
  gross_pnl?: number
  charges?: number
  net_pnl: number
  qty?: number
  lots?: number
  spot_at_entry?: number
  delta_at_entry?: number
  iv_at_entry?: number
  vix?: number
  trade_date: string
  entry_slippage_pct?: number
  strategy?: string
  regime?: string
  filter_log?: Record<string, unknown>
  symbol?: string
}

interface BacktestResponse {
  trades?: JournalTrade[]
  metrics?: Record<string, number | string | unknown>
}

const API_STRATEGIES = [
  { value: 'BOTH', label: 'ALL — Multi-strategy' },
  { value: 'ORB', label: 'ORB' },
  { value: 'VWAP', label: 'VWAP reclaim' },
  { value: 'MR', label: 'Mean reversion / fade' },
  { value: 'GAP', label: 'Gap momentum' },
] as const

const KNOWN_STRATEGIES = [
  'ORB',
  'RELAXED_ORB',
  'VWAP_RECLAIM',
  'MEAN_REVERSION',
  'RANGE_FADE',
  'EMA_PULLBACK',
  'GAP_MOMENTUM',
] as const

function normalizeExit(reason?: string): string {
  if (!reason) return ''
  const u = reason.toUpperCase()
  if (u === 'TARGET') return 'TARGET_HIT'
  return u
}

function num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return Number.isFinite(n) ? n : fallback
}

function tradeLabel(t: JournalTrade): string {
  if (t.symbol) return t.symbol
  const ot = t.option_type || (t.direction === 'PUT' ? 'PE' : 'CE')
  return `NIFTY ${t.strike} ${ot}`
}

function computeRewardRisk(t: JournalTrade): number | null {
  const risk = Math.abs(t.entry_price - t.sl_price)
  const reward = Math.abs(t.target_price - t.entry_price)
  if (!risk || risk < 1e-6) return null
  return reward / risk
}

function filterEntryStatus(v: unknown): 'pass' | 'fail' | 'info' {
  if (v === true) return 'pass'
  if (v === false) return 'fail'
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    if ('passed' in o) return o.passed ? 'pass' : 'fail'
    if ('value' in o && !('passed' in o)) return 'info'
  }
  return 'info'
}

function filterDetail(v: unknown): string {
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>
    if (typeof o.detail === 'string' && o.detail) return o.detail
    if ('value' in o && o.value !== undefined) {
      return `${o.value}`
    }
  }
  return ''
}

function filterLogForVisualizer(log: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!log) return {}
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(log)) {
    if (k === 'regime') continue
    out[k] = v
  }
  return out
}

function buildEntryReasoning(log: Record<string, unknown> | undefined): string {
  if (!log || !Object.keys(log).length) {
    return 'Entry filters were not recorded for this run; strategy rules still produced a valid signal.'
  }
  const parts: string[] = []
  for (const [key, v] of Object.entries(log)) {
    if (key === 'regime') continue
    const label = key.replace(/_/g, ' ')
    const st = filterEntryStatus(v)
    const d = filterDetail(v)
    if (d) {
      parts.push(`${label}: ${d}`)
    } else if (st === 'pass') {
      parts.push(`${label} passed`)
    } else if (st === 'fail') {
      parts.push(`${label} failed`)
    }
  }
  if (!parts.length) return 'Filter log present but no textual detail; see pills below.'
  return parts.join('. ') + '.'
}

const REGIME_BLURB: Record<string, string> = {
  STRONG_TREND_UP:   'Strong uptrend: all indicators bullish — high conviction CALL bias, breakout and continuation setups.',
  STRONG_TREND_DOWN: 'Strong downtrend: all indicators bearish — high conviction PUT bias, continuation setups preferred.',
  MILD_TREND:        'Mild trend: directional bias present but not extreme — pullback and VWAP setups work best.',
  MEAN_REVERT:       'Mean-reversion regime: price stretched from equilibrium — fades, range bounces, and VWAP entries.',
  BREAKOUT:          'Breakout regime: compression and inside bar patterns detected — breakout momentum setups preferred.',
  VOLATILE:          'Volatile regime: elevated VIX/ATR — only high-conviction gap fades and reversal setups allowed.',
}

const STRATEGY_WHY: Record<string, string> = {
  TREND_CONTINUATION: 'Trend continuation: pullback to EMA stack in a confirmed trend with VWAP support, targets resumption of primary move.',
  BREAKOUT_MOMENTUM:  'Breakout momentum: N-candle range breakout with volume surge and EMA alignment — rides fresh directional momentum.',
  REVERSAL_SNAP:      'Reversal snap: RSI extreme exhaustion combined with reversal candle pattern — high-probability mean-reversion.',
  GAP_FADE:           'Gap fade: opening gaps that statistically fill — fades over-extension at open for a quick mean-reversion trade.',
  RANGE_BOUNCE:       'Range bounce: bounce off prior-day support/resistance in a ranging market — defined risk with tight SL at level.',
  INSIDE_BAR_BREAK:   'Inside bar break: low-volatility compression breakout — low-risk entry into the next directional expansion move.',
  VWAP_CROSS:         'VWAP cross: institutional flow confirmation — cross of VWAP after prior deviation signals smart-money repositioning.',
}

function strategyWhyText(strategy?: string, regime?: string): string {
  const s = strategy || 'UNKNOWN'
  const base = STRATEGY_WHY[s] || `Strategy ${s} was selected by the multi-strategy router for this session.`
  const r = regime ? REGIME_BLURB[regime] : ''
  return r ? `${base} ${r}` : base
}

function exitAnalysisText(exitReason?: string): string {
  const e = normalizeExit(exitReason)
  if (e === 'SL_HIT') return 'Price moved against position — the protective stop triggered.'
  if (e === 'TARGET_HIT') return 'Target achieved — planned reward zone was reached.'
  if (e === 'FORCE_EXIT') return 'End of day exit — position flattened at session close rules.'
  return exitReason ? `Exit: ${exitReason.replace(/_/g, ' ')}.` : 'Exit reason not recorded.'
}

function vixContext(vix?: number): string {
  if (vix == null || !Number.isFinite(vix)) return 'VIX was not available in this row.'
  if (vix < 14) return `India VIX at ${vix.toFixed(1)} is subdued — premiums lean cheaper, moves can grind.`
  if (vix < 20) return `India VIX at ${vix.toFixed(1)} is moderate — typical intraday option risk/reward.`
  if (vix < 26) return `India VIX at ${vix.toFixed(1)} is elevated — wider swings and slippage are more likely.`
  return `India VIX at ${vix.toFixed(1)} is high — stress regime; survival and sizing matter more than precision.`
}

function computeGrade(t: JournalTrade): { grade: 'A' | 'B' | 'C' | 'D'; blurb: string } {
  const exit = normalizeExit(t.exit_reason)
  const qty = num(t.qty, (num(t.lots, 1) * 65))
  const riskAbs = Math.abs(t.entry_price - t.sl_price) * qty
  const rr = computeRewardRisk(t) ?? 0
  const win = num(t.net_pnl) > 0
  const rMult = riskAbs > 0 ? num(t.net_pnl) / riskAbs : 0

  if (exit === 'TARGET_HIT' && rr >= 1.5) {
    return { grade: 'A', blurb: 'Plan-grade: target hit with solid reward-to-risk.' }
  }
  if (win && exit === 'FORCE_EXIT') {
    return { grade: 'B', blurb: 'Held to session end but closed green.' }
  }
  if (win && exit === 'TARGET_HIT' && rr < 1.5) {
    return { grade: 'B', blurb: 'Target hit — R:R was modest versus risk.' }
  }
  if (exit === 'SL_HIT') {
    if (rMult >= -1.2) {
      return { grade: 'C', blurb: 'Stop loss — loss size stayed near defined risk.' }
    }
    return { grade: 'D', blurb: 'Stop loss — outcome worse than the nominal risk box.' }
  }
  if (win) {
    return { grade: 'B', blurb: 'Profitable trade.' }
  }
  if (num(t.net_pnl) < 0) {
    return { grade: 'D', blurb: 'Net loss after costs.' }
  }
  return { grade: 'C', blurb: 'Flat / mixed outcome.' }
}

function gradeStyles(grade: 'A' | 'B' | 'C' | 'D') {
  switch (grade) {
    case 'A':
      return { badge: 'bg-green/15 text-green-l border-green/25' }
    case 'B':
      return { badge: 'bg-cyan/12 text-cyan border-cyan/20' }
    case 'C':
      return { badge: 'bg-amber/12 text-amber border-amber/20' }
    default:
      return { badge: 'bg-red/12 text-red-l border-red/25' }
  }
}

function strategyChipClass(strategy?: string): string {
  const s = strategy || ''
  if (s.includes('ORB')) return 'bg-amber/10 text-amber border-amber/20'
  if (s.includes('VWAP')) return 'bg-cyan/10 text-cyan border-cyan/20'
  if (s.includes('MEAN') || s.includes('RANGE') || s.includes('FADE')) return 'bg-accent/10 text-accent-l border-accent/20'
  if (s.includes('EMA')) return 'bg-cyan/8 text-cyan border-cyan/15'
  if (s.includes('GAP')) return 'bg-amber/8 text-amber border-amber/15'
  return 'bg-surface text-text2 border-line/25'
}

function tradeStableId(t: JournalTrade, i: number): string {
  return `${t.trade_date}|${t.entry_ts}|${i}`
}

export function JournalPage() {
  const [trades, setTrades] = useState<JournalTrade[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [dateFilter, setDateFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState<string>('ALL')
  const [apiStrategy, setApiStrategy] = useState<string>('BOTH')
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [source, setSource] = useState<'live' | 'backtest'>('live')

  const loadJournal = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      if (source === 'live') {
        const r = await axios.get<{ trades: Record<string, unknown>[] }>('/api/trades?limit=500')
        const raw: JournalTrade[] = Array.isArray(r.data?.trades) ? (r.data.trades as unknown as JournalTrade[]) : []
        // Normalize live trade fields to match JournalTrade shape
        const list: JournalTrade[] = raw.map((t) => ({
          ...t,
          trade_date: t.trade_date || String((t as unknown as Record<string,unknown>).entry_time || (t as unknown as Record<string,unknown>).ts || '').slice(0, 10),
          entry_ts: t.entry_ts || (t as unknown as Record<string,unknown>).entry_time as string || (t as unknown as Record<string,unknown>).ts as string || '',
        }))
        setTrades(list)
      } else {
        const r = await axios.post<BacktestResponse>('/api/backtest/run', {
          strategy: apiStrategy,
          start_date: startDate,
          end_date: endDate,
        })
        const list = Array.isArray(r.data?.trades) ? r.data.trades! : []
        setTrades(list)
      }
      setExpanded(null)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err.response?.data?.detail || err.message || 'Failed to load journal')
    } finally {
      setLoading(false)
    }
  }, [source, apiStrategy, startDate, endDate])

  const strategyOptions = useMemo(() => {
    const fromData = new Set<string>()
    trades.forEach((t) => {
      if (t.strategy) fromData.add(t.strategy)
    })
    KNOWN_STRATEGIES.forEach((s) => fromData.add(s))
    return ['ALL', ...Array.from(fromData).sort()]
  }, [trades])

  const dates = useMemo(() => {
    const s = new Set<string>()
    trades.forEach((t) => {
      const d = String(t.trade_date || '').slice(0, 10)
      if (d) s.add(d)
    })
    return Array.from(s).sort().reverse()
  }, [trades])

  const filtered = useMemo(() => {
    let list = [...trades].reverse()
    if (dateFilter) list = list.filter((t) => String(t.trade_date).slice(0, 10) === dateFilter)
    if (strategyFilter !== 'ALL') list = list.filter((t) => t.strategy === strategyFilter)
    return list
  }, [trades, dateFilter, strategyFilter])

  const overallStats = useMemo(() => {
    if (!filtered.length) return null
    const wins = filtered.filter((t) => num(t.net_pnl) >= 0)
    const losses = filtered.filter((t) => num(t.net_pnl) < 0)
    const pnl = filtered.reduce((s, t) => s + num(t.net_pnl), 0)
    const charges = filtered.reduce((s, t) => s + num(t.charges), 0)
    return {
      total: filtered.length,
      wins: wins.length,
      losses: losses.length,
      pnl,
      charges,
      winRate: (wins.length / filtered.length) * 100,
      avgWin: wins.length ? wins.reduce((s, t) => s + num(t.net_pnl), 0) / wins.length : 0,
      avgLoss: losses.length ? losses.reduce((s, t) => s + num(t.net_pnl), 0) / losses.length : 0,
    }
  }, [filtered])

  const emptyAfterLoad = !loading && !error && trades.length === 0

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-green/10 flex items-center justify-center">
            <BookOpen size={18} className="text-green" />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-text1 tracking-tight">Auto Trade Journal</h1>
            <p className="text-[11px] text-text3">
              Load backtest trades, then review narratives, filters, execution quality, and grades
            </p>
          </div>
        </div>
      </motion.div>

      {/* Load panel */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-2xl p-5 neon-border"
      >
        <div className="flex items-center justify-between gap-2 mb-4">
          <div className="flex items-center gap-2">
            <Layers size={13} className="text-accent" />
            <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">
              {source === 'live' ? 'Live trades' : 'Load from backtest'}
            </span>
          </div>
          {/* Source toggle */}
          <div className="flex items-center gap-1 bg-bg rounded-xl p-1 border border-line/20">
            {(['live', 'backtest'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSource(s)}
                className={clsx(
                  'px-3 py-1 rounded-lg text-[11px] font-bold transition-all',
                  source === s
                    ? 'bg-accent text-white shadow'
                    : 'text-text3 hover:text-text1',
                )}
              >
                {s === 'live' ? 'Live' : 'Backtest'}
              </button>
            ))}
          </div>
        </div>
        {source === 'backtest' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end mb-3">
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">API strategy</label>
            <select
              value={apiStrategy}
              onChange={(e) => setApiStrategy(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 focus:border-accent/40 focus:outline-none font-semibold appearance-none cursor-pointer"
            >
              {API_STRATEGIES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">Start</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">End</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none"
            />
          </div>
        </div>
        )}
        <div className="flex">
          <motion.button
            type="button"
            onClick={loadJournal}
            disabled={loading}
            whileHover={{ scale: loading ? 1 : 1.02 }}
            whileTap={{ scale: 0.98 }}
            className={clsx(
              'flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-[12px] font-bold border transition-all',
              loading
                ? 'bg-accent/10 text-accent-l border-accent/20 cursor-wait'
                : 'bg-accent text-white border-accent hover:shadow-lg hover:shadow-accent/20',
            )}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            {loading ? 'Loading…' : source === 'live' ? 'Load Live Trades' : 'Load Journal'}
          </motion.button>
        </div>
      </motion.div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="glass-card rounded-2xl p-4 border-l-[3px] border-l-red flex items-center gap-3 neon-border"
          >
            <AlertCircle size={16} className="text-red shrink-0" />
            <span className="text-[12px] text-red-l">{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {emptyAfterLoad && (
        <div className="glass-card rounded-2xl p-14 text-center neon-border">
          <Sparkles size={22} className="text-accent mx-auto mb-3 opacity-80" />
          <p className="text-text1 font-semibold text-[14px]">No trades loaded yet</p>
          <p className="text-text3 text-[11px] mt-1 max-w-md mx-auto">
            {source === 'live'
              ? 'Press Load Live Trades to review your actual executed trades.'
              : 'Pick a date range and strategy, then press Load Journal to fetch simulated backtest trades.'}
          </p>
        </div>
      )}

      {trades.length > 0 && (
        <>
          {/* Filters + summary */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 flex-wrap"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Calendar size={12} className="text-text3" />
              <select
                value={dateFilter}
                onChange={(e) => setDateFilter(e.target.value)}
                className="bg-surface border border-line/30 rounded-xl px-3 py-1.5 text-[11px] text-text1 focus:border-accent/40 focus:outline-none font-semibold"
              >
                <option value="">All dates</option>
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <select
                value={strategyFilter}
                onChange={(e) => setStrategyFilter(e.target.value)}
                className="bg-surface border border-line/30 rounded-xl px-3 py-1.5 text-[11px] text-text1 focus:border-accent/40 focus:outline-none font-semibold"
              >
                {strategyOptions.map((s) => (
                  <option key={s} value={s}>
                    {s === 'ALL' ? 'All strategies' : s}
                  </option>
                ))}
              </select>
            </div>
            <p className="text-[10px] text-text3 font-medium">
              Showing <span className="text-text2 font-bold">{filtered.length}</span> of{' '}
              <span className="text-text2 font-bold">{trades.length}</span> loaded
            </p>
          </motion.div>

          {overallStats && (
            <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
              {[
                { label: 'Trades', value: overallStats.total, color: 'accent' as const, icon: BarChart3 },
                {
                  label: 'Net P&L',
                  value: overallStats.pnl,
                  prefix: overallStats.pnl >= 0 ? '+₹' : '-₹',
                  abs: true,
                  color: overallStats.pnl >= 0 ? ('green' as const) : ('red' as const),
                  icon: overallStats.pnl >= 0 ? TrendingUp : TrendingDown,
                },
                { label: 'Fees', value: overallStats.charges, prefix: '₹', abs: true, color: 'red' as const, icon: Crosshair },
                { label: 'Wins', value: overallStats.wins, color: 'green' as const, icon: Trophy },
                { label: 'Losses', value: overallStats.losses, color: 'red' as const, icon: Flame },
                {
                  label: 'Win rate',
                  value: overallStats.winRate,
                  suffix: '%',
                  decimals: 1,
                  color: overallStats.winRate >= 50 ? ('green' as const) : ('red' as const),
                  icon: Target,
                },
                { label: 'Avg win', value: overallStats.avgWin, prefix: '₹', decimals: 0, color: 'green' as const, icon: ArrowUpRight },
                {
                  label: 'Avg loss',
                  value: Math.abs(overallStats.avgLoss),
                  prefix: '-₹',
                  decimals: 0,
                  color: 'red' as const,
                  icon: ArrowDownRight,
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
                    className={clsx('glass-card rounded-xl p-3 border-l-[2px] neon-border', borderMap[color])}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[9px] font-bold tracking-[0.12em] uppercase text-text3">{label}</span>
                      <Icon size={10} className={textMap[color]} />
                    </div>
                    <div className={clsx('text-[14px] font-extrabold font-mono stat-val', valTextMap[color])}>
                      <CountUp
                        end={abs ? Math.abs(value) : value}
                        prefix={prefix ?? ''}
                        suffix={suffix ?? ''}
                        duration={0.6}
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

          <div className="space-y-3">
            {filtered.map((trade, i) => {
              const id = tradeStableId(trade, i)
              const isExp = expanded === id
              const isWin = num(trade.net_pnl) >= 0
              const rr = computeRewardRisk(trade)
              const rrStr = rr != null ? `${rr.toFixed(2)}x` : '—'
              const holdMin =
                trade.entry_ts && trade.exit_ts
                  ? Math.round((new Date(trade.exit_ts).getTime() - new Date(trade.entry_ts).getTime()) / 60000)
                  : null
              const log = (trade.filter_log || {}) as Record<string, unknown>
              const regimeVal =
                trade.regime ||
                (log.regime && typeof log.regime === 'object'
                  ? String((log.regime as { value?: string }).value || '')
                  : '') ||
                '—'
              const narrative = buildEntryReasoning(log)
              const why = strategyWhyText(trade.strategy, trade.regime || (regimeVal !== '—' ? regimeVal : undefined))
              const exitLine = exitAnalysisText(trade.exit_reason)
              const vixLine = vixContext(trade.vix)
              const grade = computeGrade(trade)
              const gStyle = gradeStyles(grade.grade)
              const dir = (trade.direction || '').toUpperCase()
              const optDir = dir === 'PUT' ? 'PUT' : 'CALL'
              const slip = num(trade.entry_slippage_pct)
              const ivPct = trade.iv_at_entry != null ? (num(trade.iv_at_entry) * 100).toFixed(1) : '—'
              const vizLog = filterLogForVisualizer(log)

              const execBits = [
                trade.delta_at_entry != null ? `Delta ${num(trade.delta_at_entry).toFixed(3)}` : null,
                trade.iv_at_entry != null ? `IV ~${ivPct}%` : null,
                trade.entry_slippage_pct != null ? `Entry slippage ${slip.toFixed(2)}%` : null,
                trade.charges != null ? `Charges ₹${num(trade.charges).toFixed(0)}` : null,
              ]
                .filter(Boolean)
                .join(' · ')

              return (
                <motion.div
                  key={id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i * 0.03, 0.3) }}
                  className={clsx('glass-card rounded-2xl overflow-hidden neon-border transition-all', isExp && 'ring-1 ring-accent/25')}
                >
                  <div
                    className={clsx('h-[3px]', isWin ? 'bg-gradient-to-r from-green via-green/50 to-transparent' : 'bg-gradient-to-r from-red via-red/50 to-transparent')}
                  />

                  <div className="p-5 cursor-pointer" onClick={() => setExpanded(isExp ? null : id)}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-3 min-w-0">
                        <div
                          className={clsx(
                            'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                            isWin ? 'bg-green/10' : 'bg-red/10',
                          )}
                        >
                          {isWin ? <Trophy size={18} className="text-green" /> : <Flame size={18} className="text-red" />}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[13px] font-bold text-text1 truncate">{tradeLabel(trade)}</span>
                            {trade.strategy && (
                              <span
                                className={clsx(
                                  'text-[9px] font-bold px-1.5 py-0.5 rounded border',
                                  strategyChipClass(trade.strategy),
                                )}
                              >
                                {trade.strategy}
                              </span>
                            )}
                            {regimeVal !== '—' && (
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-surface border border-line/25 text-text2 flex items-center gap-0.5">
                                <Gauge size={8} /> {regimeVal}
                              </span>
                            )}
                            <span
                              className={clsx(
                                'inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded border',
                                optDir === 'CALL' ? 'bg-green/10 text-green border-green/15' : 'bg-red/10 text-red-l border-red/15',
                              )}
                            >
                              {optDir === 'CALL' ? <ArrowUpRight size={8} /> : <ArrowDownRight size={8} />}
                              {optDir}
                            </span>
                            <span
                              className={clsx(
                                'text-[9px] font-bold px-1.5 py-0.5 rounded border',
                                isWin ? 'bg-green/10 text-green border-green/12' : 'bg-red/10 text-red-l border-red/12',
                              )}
                            >
                              {isWin ? 'WIN' : 'LOSS'}
                            </span>
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-surface border border-line/20 text-text3">
                              {normalizeExit(trade.exit_reason).replace(/_/g, ' ') || '—'}
                            </span>
                            <span
                              className={clsx(
                                'text-[9px] font-black px-1.5 py-0.5 rounded border',
                                gStyle.badge,
                              )}
                            >
                              {grade.grade}
                            </span>
                          </div>
                          <div className="text-[10px] text-text3 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="flex items-center gap-1">
                              <Calendar size={9} /> {String(trade.trade_date).slice(0, 10)}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock size={9} />
                              {trade.entry_ts &&
                                new Date(trade.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                              {holdMin != null && ` → ${holdMin}m`}
                            </span>
                            {trade.vix != null && <span>VIX {num(trade.vix).toFixed(1)}</span>}
                          </div>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className={clsx('text-lg font-extrabold font-mono stat-val', isWin ? 'text-green-l' : 'text-red-l')}>
                          {isWin ? '+' : ''}₹{num(trade.net_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </div>
                        <ChevronDown size={12} className={clsx('text-text3 transition-transform ml-auto mt-1', isExp && 'rotate-180')} />
                      </div>
                    </div>

                    <AnimatePresence>
                      {isExp && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          <div className="mt-4 pt-4 border-t border-line/15 space-y-4">
                            {/* Price grid */}
                            <div>
                              <div className="text-[10px] font-bold uppercase tracking-wider text-text3 mb-2 flex items-center gap-1">
                                <BarChart3 size={10} /> Price & risk grid
                              </div>
                              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-2">
                                {[
                                  { label: 'Entry', val: `₹${num(trade.entry_price).toFixed(2)}`, color: 'text-accent-l' },
                                  {
                                    label: 'Exit',
                                    val: trade.exit_price != null ? `₹${num(trade.exit_price).toFixed(2)}` : '—',
                                    color: isWin ? 'text-green' : 'text-red',
                                  },
                                  { label: 'SL', val: `₹${num(trade.sl_price).toFixed(2)}`, color: 'text-red-l' },
                                  { label: 'Target', val: `₹${num(trade.target_price).toFixed(2)}`, color: 'text-green-l' },
                                  {
                                    label: 'Spot',
                                    val: trade.spot_at_entry != null ? num(trade.spot_at_entry).toFixed(0) : '—',
                                    color: 'text-text1',
                                  },
                                  { label: 'R:R', val: rrStr, color: 'text-accent-l' },
                                  {
                                    label: 'Slip %',
                                    val: trade.entry_slippage_pct != null ? `${slip.toFixed(2)}%` : '—',
                                    color: 'text-amber',
                                  },
                                  {
                                    label: 'IV',
                                    val: trade.iv_at_entry != null ? `${ivPct}%` : '—',
                                    color: 'text-cyan',
                                  },
                                  {
                                    label: 'Delta',
                                    val: trade.delta_at_entry != null ? num(trade.delta_at_entry).toFixed(3) : '—',
                                    color: 'text-text1',
                                  },
                                  { label: 'VIX', val: trade.vix != null ? num(trade.vix).toFixed(1) : '—', color: 'text-text2' },
                                ].map(({ label, val, color }) => (
                                  <div key={label} className="bg-surface/50 rounded-lg p-2 border border-line/15 text-center">
                                    <div className="text-[8px] font-bold uppercase text-text3 mb-0.5">{label}</div>
                                    <div className={clsx('text-[12px] font-bold font-mono stat-val', color)}>{val}</div>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {/* Narrative */}
                            <div className="bg-surface/30 rounded-xl p-4 border border-line/15">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-text3 mb-2 flex items-center gap-1">
                                <Sparkles size={10} /> Auto narrative
                              </div>
                              <p className="text-[11px] text-text2 leading-relaxed space-y-2">
                                <span className="block">
                                  <span className="font-semibold text-text1">{trade.strategy || 'Strategy'}</span> — {why}
                                </span>
                                <span className="block text-text1/90">
                                  <span className="font-semibold text-accent-l">Regime:</span> {regimeVal}.{' '}
                                  <span className="font-semibold text-accent-l">Entry read:</span> {narrative}
                                </span>
                                <span className="block">
                                  <span className="font-semibold text-text1">Exit:</span> {exitLine}
                                </span>
                                <span className="block">
                                  <span className="font-semibold text-text1">Execution:</span>{' '}
                                  {execBits || 'Slippage / Greeks not available on this row.'}
                                </span>
                                <span className="block text-text3">{vixLine}</span>
                                <span className="block">
                                  <span className="font-semibold text-text1">Outcome:</span>{' '}
                                  <span className={clsx('font-bold', isWin ? 'text-green-l' : 'text-red-l')}>
                                    {isWin ? '+' : ''}₹{num(trade.net_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })} net
                                  </span>{' '}
                                  after charges.
                                </span>
                              </p>
                            </div>

                            {/* Grade */}
                            <div className="flex items-start gap-3 rounded-xl border border-line/15 bg-surface/20 p-3">
                              <div className={clsx('text-lg font-black px-2 py-1 rounded-lg border', gStyle.badge)}>{grade.grade}</div>
                              <div>
                                <div className="text-[10px] font-bold uppercase text-text3 tracking-wider">Trade grade</div>
                                <p className="text-[11px] text-text2 mt-0.5">{grade.blurb}</p>
                              </div>
                            </div>

                            {/* Filter log — pass / fail / info pills */}
                            {Object.keys(vizLog).length > 0 ? (
                              <div className="space-y-2">
                                <div className="text-[10px] font-bold uppercase tracking-wider text-text3 flex items-center gap-1">
                                  <Zap size={10} /> Entry filters
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                  {Object.entries(vizLog).map(([key, v], fi) => {
                                    const st = filterEntryStatus(v)
                                    const detail = filterDetail(v)
                                    return (
                                      <motion.div
                                        key={key}
                                        initial={{ opacity: 0, scale: 0.96 }}
                                        animate={{ opacity: 1, scale: 1 }}
                                        transition={{ delay: Math.min(fi * 0.04, 0.35) }}
                                        className={clsx(
                                          'flex items-start gap-2 px-2.5 py-2 rounded-xl border text-[10px] font-medium',
                                          st === 'pass' && 'bg-green/5 border-green/15 text-green',
                                          st === 'fail' && 'bg-red/5 border-red/15 text-red-l/80',
                                          st === 'info' && 'bg-surface/60 border-line/20 text-text2',
                                        )}
                                      >
                                        {st === 'pass' && <CheckCircle2 size={12} className="shrink-0 mt-0.5 text-green" />}
                                        {st === 'fail' && <XCircle size={12} className="shrink-0 mt-0.5 text-red" />}
                                        {st === 'info' && <Info size={12} className="shrink-0 mt-0.5 text-text3" />}
                                        <span className="min-w-0">
                                          <span className="block capitalize font-bold text-text1">{key.replace(/_/g, ' ')}</span>
                                          {detail ? (
                                            <span className="block text-[9px] text-text3 mt-0.5 leading-snug">{detail}</span>
                                          ) : null}
                                        </span>
                                      </motion.div>
                                    )
                                  })}
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center gap-2 text-[10px] text-text3">
                                <Info size={12} /> No filter breakdown stored for this trade.
                              </div>
                            )}

                            {/* Extra pills for regime if present */}
                            {!!log.regime && (
                              <div className="flex flex-wrap gap-1.5">
                                <span className="text-[9px] font-bold uppercase text-text3 tracking-wider mr-1 self-center">Context</span>
                                <span className="flex items-center gap-1 px-2 py-1 rounded-lg border border-cyan/20 bg-cyan/5 text-cyan text-[10px]">
                                  <Gauge size={10} /> regime:{' '}
                                  {typeof log.regime === 'object' && log.regime !== null
                                    ? String((log.regime as { value?: string }).value ?? regimeVal)
                                    : String(log.regime)}
                                </span>
                              </div>
                            )}

                            {/* Charges */}
                            <div className="rounded-xl border border-line/15 bg-surface/25 p-4">
                              <div className="text-[10px] font-bold uppercase tracking-wider text-text3 mb-3">Charges breakdown</div>
                              <div className="grid grid-cols-3 gap-3 text-center">
                                <div>
                                  <div className="text-[9px] text-text3 uppercase font-bold">Gross</div>
                                  <div className="text-[14px] font-mono font-bold text-text1">
                                    ₹{num(trade.gross_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                                  </div>
                                </div>
                                <div>
                                  <div className="text-[9px] text-text3 uppercase font-bold">Charges</div>
                                  <div className="text-[14px] font-mono font-bold text-red-l">
                                    −₹{num(trade.charges).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                                  </div>
                                </div>
                                <div>
                                  <div className="text-[9px] text-text3 uppercase font-bold">Net</div>
                                  <div className={clsx('text-[14px] font-mono font-bold', isWin ? 'text-green-l' : 'text-red-l')}>
                                    {isWin ? '+' : ''}₹{num(trade.net_pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              )
            })}
          </div>

          {filtered.length === 0 && (
            <div className="glass-card rounded-2xl p-10 text-center text-text3 text-[12px] neon-border">
              No trades match the current filters.
            </div>
          )}
        </>
      )}
    </div>
  )
}
