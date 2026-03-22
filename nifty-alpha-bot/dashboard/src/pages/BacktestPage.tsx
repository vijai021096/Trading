import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  FlaskConical, Play, Loader2, TrendingUp, TrendingDown, Target, BarChart3,
  Calendar, AlertCircle, ChevronDown, ArrowUpRight, Gauge, Trophy, Flame,
  BarChart2, LineChart, Layers, Info, LayoutGrid, Activity
} from 'lucide-react'
import { AreaChart, Area, BarChart, Bar, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, Cell } from 'recharts'

interface BacktestResult {
  metrics: Record<string, any>
  monthly?: Record<string, any>[]
  equity_curve?: { date: string; equity: number }[]
  trades?: any[]
}

const STRATEGY_COLOR_HEX: Record<string, string> = {
  ORB: '#f59e0b',
  VWAP_RECLAIM: '#06b6d4',
  EMA_PULLBACK: '#6366f1',
  MEAN_REVERSION: '#10b981',
  RELAXED_ORB: '#8b5cf6',
  RANGE_FADE: '#ec4899',
}

function strategyColor(strategy: string): string {
  return STRATEGY_COLOR_HEX[strategy] ?? '#64748b'
}

export function BacktestPage() {
  const [strategy, setStrategy] = useState('BOTH')
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [showTrades, setShowTrades] = useState(false)

  const run = async () => {
    setLoading(true); setError(''); setResult(null)
    try {
      const r = await axios.post('/api/backtest/run', { strategy, start_date: startDate, end_date: endDate })
      setResult(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }

  const m = result?.metrics || {}

  const strategyBreakdownRows = useMemo(() => {
    const trades = result?.trades ?? []
    const map = new Map<string, number[]>()
    for (const t of trades) {
      const s = String(t.strategy ?? 'UNKNOWN')
      const pnl = Number(t.net_pnl ?? 0)
      if (!map.has(s)) map.set(s, [])
      map.get(s)!.push(pnl)
    }
    return Array.from(map.entries()).map(([strategy, pnls]) => {
      const n = pnls.length
      const winPnls = pnls.filter(p => p > 0)
      const lossPnls = pnls.filter(p => p < 0)
      const wins = winPnls.length
      const grossWin = winPnls.reduce((a, b) => a + b, 0)
      const grossLossAbs = Math.abs(lossPnls.reduce((a, b) => a + b, 0))
      const netPnl = pnls.reduce((a, b) => a + b, 0)
      return {
        strategy,
        trades: n,
        wins,
        wrPct: n ? (wins / n) * 100 : 0,
        netPnl,
        avgWin: wins ? grossWin / wins : 0,
        avgLossMag: lossPnls.length ? grossLossAbs / lossPnls.length : 0,
        profitFactor: grossLossAbs > 0 ? grossWin / grossLossAbs : grossWin > 0 ? Infinity : 0,
      }
    }).sort((a, b) => b.netPnl - a.netPnl)
  }, [result?.trades])

  const regimeDist = useMemo(() => {
    const trades = result?.trades ?? []
    const counts = { TRENDING: 0, RANGING: 0, VOLATILE: 0, OTHER: 0 }
    for (const t of trades) {
      const r = String(t.regime ?? '').toUpperCase()
      if (r === 'TRENDING' || r === 'RANGING' || r === 'VOLATILE') counts[r] += 1
      else counts.OTHER += 1
    }
    return counts
  }, [result?.trades])

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-accent/15 flex items-center justify-center">
            <FlaskConical size={22} className="text-accent" />
          </div>
          <div>
            <h1 className="text-xl font-black text-text1 tracking-tight">Backtester</h1>
            <p className="text-sm text-text3">Walk-forward simulation with historical Nifty & VIX data</p>
          </div>
        </div>
        <div className="bg-amber/8 border border-amber/20 rounded-xl px-4 py-2 max-w-sm">
          <div className="text-xs font-bold text-amber flex items-center gap-1"><AlertCircle size={12} /> Data Note</div>
          <div className="text-xs text-text3 mt-0.5">yfinance provides max ~60 days of 5-min intraday data for NIFTY. For longer backtests, daily data is used.</div>
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-2xl p-4 neon-border border-l-[3px] border-l-accent/50">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
            <Info size={16} className="text-accent" />
          </div>
          <div>
            <div className="text-[11px] font-bold tracking-[0.12em] uppercase text-text2">Execution Realism</div>
            <p className="text-[12px] text-text3 mt-1 leading-relaxed">
              All results include: IV smile adjustment, IV crush modeling, dynamic slippage (VIX & DTE based),
              intraday SL/target via high/low simulation, realistic brokerage charges
            </p>
          </div>
        </div>
      </motion.div>

      {/* Config panel */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-2xl p-5 neon-border">
        <div className="flex items-center gap-2 mb-4">
          <Layers size={13} className="text-accent" />
          <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Configuration</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">Strategy</label>
            <select value={strategy} onChange={e => setStrategy(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 focus:border-accent/40 focus:outline-none transition-colors font-semibold appearance-none cursor-pointer">
              <option value="BOTH">ALL — Multi-Strategy (Auto-Select)</option>
              <option value="ORB">ORB — Opening Range Breakout</option>
              <option value="VWAP">VWAP — Volume Weighted Avg Price</option>
              <option value="MR">MR — Mean-Reversion + Range Fade</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">Start Date</label>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none transition-colors" />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-text3 uppercase tracking-wider mb-1.5">End Date</label>
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
              className="w-full bg-surface border border-line/30 rounded-xl px-3 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none transition-colors" />
          </div>
          <motion.button onClick={run} disabled={loading}
            whileHover={{ scale: loading ? 1 : 1.03 }} whileTap={{ scale: 0.97 }}
            className={clsx('flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-[12px] font-bold transition-all border',
              loading ? 'bg-accent/10 text-accent-l border-accent/20 cursor-wait' : 'bg-accent text-white border-accent hover:shadow-lg hover:shadow-accent/20')}>
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {loading ? 'Running...' : 'Run Backtest'}
          </motion.button>
        </div>
      </motion.div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="glass-card rounded-2xl p-4 border-l-[3px] border-l-red flex items-center gap-3">
            <AlertCircle size={16} className="text-red shrink-0" />
            <span className="text-[12px] text-red-l">{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Loading */}
      <AnimatePresence>
        {loading && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="glass-card rounded-2xl p-10 text-center">
            <Loader2 size={28} className="animate-spin text-accent mx-auto mb-3" />
            <p className="text-text1 font-semibold">Running {strategy} backtest...</p>
            <p className="text-text3 text-[11px] mt-1">Fetching Nifty spot & VIX data, simulating trades</p>
            <div className="mt-4 h-1 rounded-full bg-surface max-w-xs mx-auto overflow-hidden">
              <motion.div className="h-full bg-accent rounded-full" animate={{ x: ['-100%', '100%'] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }} style={{ width: '40%' }} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results */}
      {result && !loading && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">

          {/* Metrics grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              { label: 'Total Return', key: 'total_net_pnl', prefix: '₹', color: (m.total_net_pnl ?? 0) >= 0 ? 'green' : 'red', icon: TrendingUp },
              { label: 'Trades', key: 'total_trades', color: 'accent', icon: BarChart3 },
              { label: 'Win Rate', key: 'win_rate_pct', suffix: '%', decimals: 1, color: (m.win_rate_pct ?? 0) >= 50 ? 'green' : 'red', icon: Target },
              { label: 'Sharpe', key: 'sharpe_ratio', decimals: 2, color: (m.sharpe_ratio ?? 0) >= 1 ? 'green' : 'amber', icon: Gauge },
              { label: 'Max DD', key: 'max_drawdown_abs', prefix: '₹', color: 'red', icon: TrendingDown },
              { label: 'P. Factor', key: 'profit_factor', decimals: 2, color: (m.profit_factor ?? 0) >= 1 ? 'green' : 'red', icon: Trophy },
            ].map(({ label, key, prefix, suffix, decimals, color, icon: Icon }) => {
              const borderMap = { green: 'border-l-green', red: 'border-l-red', accent: 'border-l-accent', amber: 'border-l-amber' } as const
              const textMap = { green: 'text-green', red: 'text-red', accent: 'text-accent', amber: 'text-amber' } as const
              const valTextMap = { green: 'text-green-l', red: 'text-red-l', accent: 'text-accent-l', amber: 'text-amber' } as const
              return (
              <motion.div key={key} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                className={clsx('glass-card rounded-xl p-3.5 border-l-[2px] neon-border', borderMap[color as keyof typeof borderMap])}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[9px] font-bold tracking-[0.15em] uppercase text-text3">{label}</span>
                  <Icon size={11} className={textMap[color as keyof typeof textMap]} />
                </div>
                <div className={clsx('text-[18px] font-extrabold font-mono stat-val', valTextMap[color as keyof typeof valTextMap])}>
                  <CountUp end={Math.abs(m[key] ?? 0)} prefix={prefix ?? ''} suffix={suffix ?? ''} duration={0.8} decimals={decimals ?? 0} separator="," preserveValue />
                </div>
              </motion.div>
            )})}
          </div>

          {/* Equity curve */}
          {result.equity_curve && result.equity_curve.length > 0 && (
            <div className="glass-card rounded-2xl p-5 neon-border">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
                  <LineChart size={13} className="text-accent" />
                </div>
                <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Equity Curve</span>
              </div>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={result.equity_curve}>
                    <defs>
                      <linearGradient id="btGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#6366f1" stopOpacity={0.2} />
                        <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1c2244" />
                    <XAxis dataKey="date" tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false}
                      tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
                    <Tooltip contentStyle={{ background: '#111631', border: '1px solid #1c2244', borderRadius: '10px', fontSize: 11 }}
                      formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'Equity']} />
                    <Area type="monotone" dataKey="equity" stroke="#6366f1" strokeWidth={2} fill="url(#btGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Monthly returns */}
          {result.monthly && result.monthly.length > 0 && (
            <div className="glass-card rounded-2xl p-5 neon-border">
              <div className="flex items-center gap-2 mb-3">
                <Calendar size={13} className="text-cyan" />
                <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Monthly Returns</span>
              </div>
              <div className="h-[180px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={result.monthly}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1c2244" />
                    <XAxis dataKey="month" tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false}
                      tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
                    <Tooltip contentStyle={{ background: '#111631', border: '1px solid #1c2244', borderRadius: '10px', fontSize: 11 }}
                      formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'Return']} />
                    <Bar dataKey="return" radius={[4, 4, 0, 0]}>
                      {result.monthly.map((d: any, i: number) => (
                        <Cell key={i} fill={(d.return ?? 0) >= 0 ? '#10b981' : '#ef4444'} opacity={0.7} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {result.trades && result.trades.length > 0 && strategyBreakdownRows.length > 0 && (
            <div className="glass-card rounded-2xl p-5 neon-border space-y-5">
              <div className="flex items-center gap-2">
                <LayoutGrid size={13} className="text-accent" />
                <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Strategy Breakdown</span>
              </div>
              <div className="overflow-x-auto rounded-xl border border-line/15">
                <table className="w-full text-[11px] min-w-[720px]">
                  <thead>
                    <tr className="border-b border-line/20 bg-card/40">
                      <th className="text-left py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Strategy</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Trades</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Wins</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">WR%</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Net P&amp;L</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Avg Win</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Avg Loss</th>
                      <th className="text-right py-2.5 px-3 text-[9px] font-bold tracking-wider text-text3 uppercase">Profit Factor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {strategyBreakdownRows.map((row) => {
                      const c = strategyColor(row.strategy)
                      return (
                        <tr key={row.strategy} className="border-b border-line/8 hover:bg-card/30">
                          <td className="py-2.5 px-3">
                            <span className="inline-flex items-center gap-2 font-bold text-text1">
                              <span className="w-1.5 h-4 rounded-full shrink-0" style={{ backgroundColor: c }} />
                              <span style={{ color: c }}>{row.strategy.replace(/_/g, ' ')}</span>
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-text2">{row.trades}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-text2">{row.wins}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-text2">{row.wrPct.toFixed(1)}</td>
                          <td className={clsx('py-2.5 px-3 text-right font-mono font-bold', row.netPnl >= 0 ? 'text-green' : 'text-red')}>
                            {row.netPnl >= 0 ? '+' : ''}₹{row.netPnl.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-green-l">₹{row.avgWin.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-red-l">₹{row.avgLossMag.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>
                          <td className="py-2.5 px-3 text-right font-mono text-text1">
                            {row.profitFactor === Infinity ? '∞' : row.profitFactor.toFixed(2)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div>
                <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2">Total P&amp;L by strategy</div>
                <div className="h-[220px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={strategyBreakdownRows.map(r => ({ name: r.strategy.replace(/_/g, ' '), pnl: r.netPnl }))} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1c2244" />
                      <XAxis dataKey="name" tick={{ fill: '#4b5c82', fontSize: 9 }} axisLine={false} tickLine={false} interval={0} angle={-18} textAnchor="end" height={56} />
                      <YAxis tick={{ fill: '#4b5c82', fontSize: 10 }} axisLine={false} tickLine={false}
                        tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
                      <Tooltip contentStyle={{ background: '#111631', border: '1px solid #1c2244', borderRadius: '10px', fontSize: 11 }}
                        formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'Net P&L']} />
                      <Bar dataKey="pnl" radius={[4, 4, 0, 0]} maxBarSize={48}>
                        {strategyBreakdownRows.map((r) => (
                          <Cell key={r.strategy} fill={r.netPnl >= 0 ? '#10b981' : '#ef4444'} opacity={0.85} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )}

          {result.trades && result.trades.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              className="glass-card rounded-2xl p-5 neon-border">
              <div className="flex items-center gap-2 mb-4">
                <Activity size={13} className="text-cyan" />
                <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Regime Distribution</span>
              </div>
              {(() => {
                const total = result.trades!.length
                const rows = [
                  { key: 'TRENDING', label: 'Trending', color: '#6366f1' },
                  { key: 'RANGING', label: 'Ranging', color: '#06b6d4' },
                  { key: 'VOLATILE', label: 'Volatile', color: '#f59e0b' },
                ] as const
                const other = regimeDist.OTHER
                return (
                  <div className="space-y-3">
                    {rows.map(({ key, label, color }) => {
                      const n = regimeDist[key]
                      const pct = total ? (n / total) * 100 : 0
                      return (
                        <div key={key}>
                          <div className="flex justify-between text-[11px] mb-1">
                            <span className="font-bold" style={{ color }}>{label}</span>
                            <span className="font-mono text-text2">{n} <span className="text-text3">({pct.toFixed(0)}%)</span></span>
                          </div>
                          <div className="h-2 rounded-full bg-surface overflow-hidden">
                            <motion.div className="h-full rounded-full" style={{ backgroundColor: color }}
                              initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.5, ease: 'easeOut' }} />
                          </div>
                        </div>
                      )
                    })}
                    {other > 0 && (
                      <div className="text-[10px] text-text3 pt-1 border-t border-line/10">
                        Other / unspecified regime: {other} trade{other !== 1 ? 's' : ''}
                      </div>
                    )}
                  </div>
                )
              })()}
            </motion.div>
          )}

          {/* Additional metrics */}
          <div className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center gap-2 mb-4">
              <BarChart2 size={13} className="text-accent" />
              <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Detailed Metrics</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-8 gap-y-2.5">
              {Object.entries(m).map(([key, val]) => (
                <div key={key} className="flex justify-between py-1 border-b border-line/10">
                  <span className="text-[11px] text-text3 capitalize">{key.replace(/_/g, ' ')}</span>
                  <span className="text-[11px] font-bold font-mono text-text1">
                    {typeof val === 'number' ? (Math.abs(val) >= 100 ? `₹${val.toLocaleString('en-IN')}` : val.toFixed(2)) : String(val)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Trade list toggle */}
          {result.trades && result.trades.length > 0 && (
            <div className="glass-card rounded-2xl overflow-hidden neon-border">
              <button onClick={() => setShowTrades(!showTrades)}
                className="w-full flex items-center justify-between px-5 py-3 border-b border-line/20 hover:bg-card/30 transition-colors">
                <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">
                  Backtest Trades ({result.trades.length})
                </span>
                <ChevronDown size={14} className={clsx('text-text3 transition-transform', showTrades && 'rotate-180')} />
              </button>
              {showTrades && (
                <div className="overflow-x-auto max-h-[400px]">
                  <table className="w-full text-[11px]">
                    <thead className="sticky top-0 bg-panel">
                      <tr className="border-b border-line/20">
                        <th className="text-left py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">Date</th>
                        <th className="text-left py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">Dir</th>
                        <th className="text-right py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">Entry</th>
                        <th className="text-right py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">Exit</th>
                        <th className="text-left py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">Reason</th>
                        <th className="text-right py-2 px-4 text-[9px] font-bold tracking-wider text-text3 uppercase">P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t: any, i: number) => (
                        <tr key={i} className="border-b border-line/8 hover:bg-card/30">
                          <td className="py-2 px-4 font-mono text-text3">{t.date || t.trade_date}</td>
                          <td className="py-2 px-4">
                            <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                              t.direction === 'CALL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>{t.direction}</span>
                          </td>
                          <td className="py-2 px-4 text-right font-mono text-text2">₹{(t.entry_price ?? 0).toFixed(1)}</td>
                          <td className="py-2 px-4 text-right font-mono text-text2">₹{(t.exit_price ?? 0).toFixed(1)}</td>
                          <td className="py-2 px-4">
                            <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                              t.exit_reason === 'TARGET' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                              {t.exit_reason?.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className={clsx('py-2 px-4 text-right font-mono font-bold', (t.net_pnl ?? 0) >= 0 ? 'text-green' : 'text-red')}>
                            {(t.net_pnl ?? 0) >= 0 ? '+' : ''}₹{(t.net_pnl ?? 0).toLocaleString('en-IN')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </motion.div>
      )}
    </div>
  )
}
