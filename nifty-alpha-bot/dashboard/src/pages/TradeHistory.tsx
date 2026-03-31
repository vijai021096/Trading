/**
 * TradeHistory — full performance analytics:
 *   hero stats • equity curve • strategy breakdown • trade table with filter log.
 */
import { Fragment, useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  BarChart3, TrendingUp, TrendingDown, Calendar, Trophy, Target,
  Flame, ChevronDown, Loader2, RefreshCw, AlertCircle, Activity,
  Wallet, CheckCircle2, XCircle, Brain, ChevronRight, Filter,
  ArrowUpRight, ArrowDownRight, Percent, Zap,
} from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Cell } from 'recharts'
import type { Trade } from '../stores/tradingStore'

type ExtTrade = Trade & {
  regime?: string; qty?: number;
  pnl?: number          // alias for net_pnl for convenience
  entry_slippage_pct?: number; delta_at_entry?: number
  filter_log?: Record<string, boolean | { passed?: boolean; value?: unknown; detail?: string }>
}

function fmt(n: number, d = 0): string {
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`
}

function normalize(raw: Record<string, unknown>): ExtTrade {
  const strike  = Number(raw.strike ?? 0)
  const opt     = String(raw.option_type ?? 'CE')
  const netPnl  = raw.pnl != null ? Number(raw.pnl) : raw.net_pnl != null ? Number(raw.net_pnl) : 0
  return {
    entry_ts:     String(raw.entry_ts ?? ''),
    exit_ts:     raw.exit_ts ? String(raw.exit_ts) : undefined,
    symbol:       raw.symbol ? String(raw.symbol) : `NIFTY ${strike} ${opt}`,
    direction:    String(raw.direction ?? ''),
    option_type:  String(raw.option_type ?? ''),
    strike,       expiry: String(raw.expiry ?? ''),
    strategy:     String(raw.strategy ?? ''),
    entry_price:  Number(raw.entry_price ?? 0),
    exit_price:   raw.exit_price ? Number(raw.exit_price) : undefined,
    net_pnl:      netPnl,
    pnl:          netPnl,
    sl_price:     Number(raw.sl_price ?? 0),
    target_price: Number(raw.target_price ?? 0),
    spot_at_entry:Number(raw.spot_at_entry ?? 0),
    vix:          Number(raw.vix ?? 0),
    trade_date:   String(raw.trade_date ?? raw.entry_ts ?? ''),
    exit_reason:  raw.exit_reason ? String(raw.exit_reason) : undefined,
    lots:         Number(raw.lots ?? 1),
    regime:       raw.regime ? String(raw.regime) : undefined,
    filter_log:   (raw.filter_log as any) ?? undefined,
  }
}

const STRAT_COLORS: Record<string, string> = {
  TREND_CONTINUATION:   '#f59e0b',
  BREAKOUT_MOMENTUM:    '#8b5cf6',
  REVERSAL_SNAP:        '#22c55e',
  GAP_FADE:             '#06b6d4',
  INSIDE_BAR_BREAK:     '#ec4899',
  VWAP_CROSS:           '#14b8a6',
  ORB:                  '#f97316',
  EMA_PULLBACK:         '#a78bfa',
  VWAP_RECLAIM:         '#34d399',
}

function stratColor(s: string) { return STRAT_COLORS[s] ?? '#475569' }

/* ── Stat hero card ──────────────────────────────────────────────── */
function StatCard({ label, value, sub, color = 'text-text1', icon: Icon }:
  { label: string; value: string | number; sub?: string; color?: string; icon?: typeof Activity }) {
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="label">{label}</span>
        {Icon && <Icon size={14} className="text-text3" />}
      </div>
      <div className={clsx('text-2xl font-black font-mono stat-val', color)}>
        {typeof value === 'number' ? (
          <CountUp end={value} duration={0.8} decimals={0} separator="," prefix={color.includes('green') ? '+' : ''} />
        ) : value}
      </div>
      {sub && <div className="text-[10px] text-text3 mt-1">{sub}</div>}
    </div>
  )
}

/* ── Filter quality badge ────────────────────────────────────────── */
function QualityBadge({ filterLog }: { filterLog?: ExtTrade['filter_log'] }) {
  if (!filterLog) return null
  const entries = Object.values(filterLog)
  const passed  = entries.filter(v => v === true || (v as any)?.passed === true).length
  const total   = entries.length
  if (!total) return null
  const pct   = passed / total
  const grade = pct >= 0.95 ? 'A+' : pct >= 0.8 ? 'A' : pct >= 0.65 ? 'B' : 'C'
  return (
    <span className={clsx(
      'text-[9px] font-black px-1.5 py-0.5 rounded border',
      grade === 'A+' ? 'bg-green/10 text-green border-green/25'
        : grade === 'A'  ? 'bg-accent/10 text-accent border-accent/25'
        : 'bg-surface text-text3 border-line/30'
    )}>{grade} {passed}/{total}</span>
  )
}

/* ── Individual trade row ───────────────────────────────────────── */
function TradeRow({ trade, idx }: { trade: ExtTrade; idx: number }) {
  const [open, setOpen] = useState(false)
  const pnl     = trade.pnl ?? 0
  const win     = pnl > 0
  const isCall  = trade.direction === 'CALL' || trade.option_type === 'CE'
  const date    = trade.entry_ts ? new Date(trade.entry_ts).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : ''
  const time    = trade.entry_ts ? new Date(trade.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : ''
  const filters = trade.filter_log ? Object.entries(trade.filter_log) : []

  return (
    <Fragment>
      <tr
        onClick={() => filters.length > 0 && setOpen(o => !o)}
        className={clsx('transition-all group', filters.length > 0 && 'cursor-pointer')}
      >
        <td>
          <div className="font-mono text-[11px] text-text1">{date}</div>
          <div className="font-mono text-[10px] text-text3">{time}</div>
        </td>
        <td>
          <div className="flex items-center gap-1.5">
            <span className={clsx(
              'text-[10px] font-bold px-1.5 py-0.5 rounded border',
              isCall ? 'bg-green/10 text-green border-green/25' : 'bg-red/10 text-red-l border-red/25'
            )}>{trade.direction || trade.option_type}</span>
            <span className="text-[10px] text-text2 font-mono">{trade.symbol}</span>
          </div>
          <div className="text-[9px] text-text3 mt-0.5 flex items-center gap-1">
            <span style={{ color: stratColor(trade.strategy) }}>●</span>
            {trade.strategy.replace(/_/g, ' ')}
          </div>
        </td>
        <td className="text-right">
          <div className="font-mono text-[11px] text-text2">{trade.entry_price.toFixed(1)}</div>
          {trade.exit_price && <div className="font-mono text-[10px] text-text3">{trade.exit_price.toFixed(1)}</div>}
        </td>
        <td className="text-right">
          <div className={clsx(
            'font-mono font-black text-[12px] stat-val',
            win ? 'text-green' : 'text-red-l'
          )}>
            {win ? '+' : ''}{fmt(pnl)}
          </div>
          <div className="text-[9px] text-text3">{trade.exit_reason ?? ''}</div>
        </td>
        <td className="text-right">
          <div className="flex items-center justify-end gap-1.5">
            <QualityBadge filterLog={trade.filter_log} />
            {filters.length > 0 && (
              open ? <ChevronDown size={11} className="text-text3" /> : <ChevronRight size={11} className="text-text3" />
            )}
          </div>
        </td>
      </tr>
      {open && filters.length > 0 && (
        <tr>
          <td colSpan={5} className="p-0 border-0">
            <motion.div
              initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden bg-bg/60 border-b border-line/20"
            >
              <div className="p-4">
                <div className="label mb-2 flex items-center gap-1"><Brain size={10} /> Filter Log</div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1.5">
                  {filters.map(([k, v]) => {
                    const ok   = v === true || (v as any)?.passed === true
                    const fail = v === false || (v as any)?.passed === false
                    return (
                      <div key={k} className={clsx(
                        'flex items-center gap-1.5 px-2 py-1 rounded-lg border text-[10px]',
                        ok ? 'bg-green/6 border-green/15 text-green' : fail ? 'bg-red/6 border-red/15 text-red-l/70' : 'bg-surface border-line/25 text-text3'
                      )}>
                        {ok ? <CheckCircle2 size={9} /> : fail ? <XCircle size={9} /> : <div className="w-2 h-2 rounded-full bg-text3/40" />}
                        <span className="truncate capitalize">{k.replace(/_/g, ' ')}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </motion.div>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

/* ── Main page ───────────────────────────────────────────────────── */
export function TradeHistory() {
  const [trades, setTrades]   = useState<ExtTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter]   = useState('All')
  const [sort, setSort]       = useState<'date' | 'pnl'>('date')

  const load = async () => {
    setLoading(true)
    try {
      const r = await axios.get('/api/trades', { params: { limit: 500 } })
      const raw: any[] = r.data?.trades ?? r.data ?? []
      setTrades(raw.map(normalize))
    } catch {}
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const strategies = useMemo(() => ['All', ...Array.from(new Set(trades.map(t => t.strategy).filter(Boolean)))], [trades])

  const filtered = useMemo(() => {
    let out = filter === 'All' ? trades : filter === 'Wins' ? trades.filter(t => (t.pnl ?? 0) > 0) : filter === 'Losses' ? trades.filter(t => (t.pnl ?? 0) < 0) : trades.filter(t => t.strategy === filter)
    if (sort === 'pnl') out = [...out].sort((a, b) => (b.pnl ?? 0) - (a.pnl ?? 0))
    return out
  }, [trades, filter, sort])

  const stats = useMemo(() => {
    const wins   = trades.filter(t => (t.pnl ?? 0) > 0)
    const losses = trades.filter(t => (t.pnl ?? 0) < 0)
    const total  = trades.reduce((a, t) => a + (t.pnl ?? 0), 0)
    const avg    = trades.length ? total / trades.length : 0
    const bestPnl= Math.max(0, ...trades.map(t => t.pnl ?? 0))
    const streak = (() => {
      let cur = 0, max = 0
      for (const t of trades) { if ((t.pnl ?? 0) > 0) { cur++; max = Math.max(max, cur) } else cur = 0 }
      return max
    })()
    // equity curve
    let running = 0
    const equity = trades.map(t => { running += (t.pnl ?? 0); return { date: t.entry_ts?.slice(5, 10) ?? '', equity: running } })
    // strategy breakdown
    const byStrat = new Map<string, { pnl: number; count: number; wins: number }>()
    for (const t of trades) {
      const s = t.strategy || 'Unknown'
      const cur = byStrat.get(s) ?? { pnl: 0, count: 0, wins: 0 }
      cur.pnl += t.pnl ?? 0; cur.count++; if ((t.pnl ?? 0) > 0) cur.wins++
      byStrat.set(s, cur)
    }
    return { wins: wins.length, losses: losses.length, total, avg, bestPnl, streak, equity, byStrat }
  }, [trades])

  const winRate = trades.length ? (stats.wins / trades.length * 100) : 0

  return (
    <div className="flex-1 overflow-y-auto p-3 lg:p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center">
            <BarChart3 size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-lg font-black text-text1">Trade Performance</h1>
            <p className="text-[11px] text-text3">{trades.length} trades tracked</p>
          </div>
        </div>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-line/30 text-[11px] text-text3 hover:text-accent hover:border-accent/30 transition-all">
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Refresh
        </button>
      </div>

      {/* Hero stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-3 mb-5">
        <StatCard label="Total P&L" icon={Wallet}
          value={Math.round(stats.total)}
          color={stats.total >= 0 ? 'text-green' : 'text-red-l'}
          sub={stats.total >= 0 ? 'net profit' : 'net loss'} />
        <StatCard label="Win Rate" icon={Percent}
          value={`${winRate.toFixed(0)}%`}
          color={winRate >= 55 ? 'text-green' : winRate >= 40 ? 'text-amber' : 'text-red-l'}
          sub={`${stats.wins}W / ${stats.losses}L`} />
        <StatCard label="Trades" icon={Activity}
          value={trades.length} color="text-text1" sub="total taken" />
        <StatCard label="Avg P&L" icon={Target}
          value={`${stats.avg >= 0 ? '+' : ''}${fmt(stats.avg)}`}
          color={stats.avg >= 0 ? 'text-green' : 'text-red-l'}
          sub="per trade" />
        <StatCard label="Best Trade" icon={Trophy}
          value={fmt(stats.bestPnl)} color="text-accent" sub="single trade" />
        <StatCard label="Win Streak" icon={Flame}
          value={stats.streak} color="text-amber" sub="consecutive wins" />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
        {/* Equity curve */}
        <div className="lg:col-span-2 glass-card rounded-2xl p-4">
          <div className="label mb-3">Equity Curve</div>
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={stats.equity} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stats.total >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={stats.total >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(27,45,74,0.5)" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#3d5478' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: '#3d5478' }} tickLine={false} axisLine={false} tickFormatter={v => `₹${v > 999 ? (v/1000).toFixed(1)+'k' : v}`} />
              <Tooltip contentStyle={{ background: '#0e1629', border: '1px solid #1b2d4a', borderRadius: 10, fontSize: 11 }}
                formatter={(v: number) => [fmt(v), 'Equity']} />
              <Area type="monotone" dataKey="equity" stroke={stats.total >= 0 ? '#22c55e' : '#ef4444'}
                strokeWidth={2} fill="url(#eq)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Strategy breakdown */}
        <div className="glass-card rounded-2xl p-4">
          <div className="label mb-3">By Strategy</div>
          {stats.byStrat.size === 0 ? (
            <div className="text-text3 text-xs text-center py-6">No data</div>
          ) : (
            <div className="space-y-2">
              {[...stats.byStrat.entries()].sort((a, b) => b[1].pnl - a[1].pnl).map(([strat, d]) => {
                const wr = d.count > 0 ? d.wins / d.count * 100 : 0
                return (
                  <div key={strat}>
                    <div className="flex items-center justify-between text-[10px] mb-1">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full" style={{ background: stratColor(strat) }} />
                        <span className="text-text2 truncate max-w-[100px]">{strat.replace(/_/g, ' ')}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[10px] text-text3">{wr.toFixed(0)}% WR</span>
                        <span className={clsx('font-mono font-bold', d.pnl >= 0 ? 'text-green' : 'text-red-l')}>
                          {d.pnl >= 0 ? '+' : ''}{fmt(d.pnl)}
                        </span>
                      </div>
                    </div>
                    <div className="h-1 rounded-full bg-surface overflow-hidden">
                      <div className="h-full rounded-full" style={{
                        width: `${wr}%`,
                        background: stratColor(strat)
                      }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Filters + table */}
      <div className="glass-card rounded-2xl overflow-hidden">
        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2 p-4 border-b border-line/25">
          <Filter size={12} className="text-text3 shrink-0" />
          <div className="flex flex-wrap gap-1.5">
            {['All', 'Wins', 'Losses', ...strategies.slice(1)].map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={clsx(
                  'px-2.5 py-1 rounded-lg text-[10px] font-bold border transition-all',
                  filter === f
                    ? 'bg-accent text-bg border-accent'
                    : 'bg-surface text-text3 border-line/30 hover:border-accent/30 hover:text-text2'
                )}>{f.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1.5 text-[10px]">
            <span className="text-text3">Sort:</span>
            {(['date', 'pnl'] as const).map(s => (
              <button key={s} onClick={() => setSort(s)}
                className={clsx('px-2 py-0.5 rounded border transition-all',
                  sort === s ? 'bg-accent/10 text-accent border-accent/25' : 'text-text3 border-line/30 hover:text-text2'
                )}>{s}</button>
            ))}
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex items-center justify-center py-16 gap-3 text-text3">
            <Loader2 size={18} className="animate-spin text-accent" />
            Loading trades...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16 text-text3 text-sm">No trades match this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full data-table">
              <thead>
                <tr>
                  <th>Date / Time</th>
                  <th>Symbol · Strategy</th>
                  <th className="text-right">Entry / Exit</th>
                  <th className="text-right">P&L</th>
                  <th className="text-right">Quality</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => <TradeRow key={`${t.entry_ts}-${i}`} trade={t} idx={i} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}