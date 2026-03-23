import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  ScrollText, Filter, Search, ArrowUpRight, ArrowDownRight,
  CheckCircle2, XCircle, AlertTriangle, Radio, Clock, Zap,
  ChevronDown, RefreshCw, Loader2, Eye, EyeOff, Key
} from 'lucide-react'

interface FilterVal {
  passed?: boolean
  value?: number | string
  detail?: string
}

interface LogEntry {
  ts: string
  event: string
  filters?: Record<string, boolean | FilterVal>
  all_passed?: boolean
  [key: string]: any
}

const EVENT_TYPES = [
  { id: 'ALL',                label: 'All',            color: 'text3'  },
  { id: 'SCAN_CYCLE',        label: 'Scan Cycle',     color: 'accent' },
  { id: 'TREND_DETECTED',    label: 'Trend',          color: 'green'  },
  { id: 'REGIME_DETECTED',   label: 'Regime',         color: 'cyan'   },
  { id: 'ORB_SCAN',          label: 'ORB',            color: 'amber'  },
  { id: 'EMA_PULLBACK_SCAN', label: 'EMA Pullback',   color: 'accent' },
  { id: 'MOMENTUM_SCAN',     label: 'Momentum',       color: 'green'  },
  { id: 'RECLAIM_SCAN',      label: 'VWAP',           color: 'cyan'   },
  { id: 'ENTRY',             label: 'Entries',        color: 'green'  },
  { id: 'TRADE_CLOSED',      label: 'Exits',          color: 'accent' },
  { id: 'RISK_BLOCKED',      label: 'Risk Blocked',   color: 'red'    },
  { id: 'SLM_EXECUTED',      label: 'SL-M Fills',     color: 'red'    },
  { id: 'BROKER_SYNC_CLOSED',label: 'Broker Sync',    color: 'amber'  },
  { id: 'KITE_AUTH',         label: 'Kite Auth',      color: 'accent' },
  { id: 'HEARTBEAT',         label: 'Heartbeat',      color: 'text3'  },
  { id: 'LOOP_ERROR',        label: 'Errors',         color: 'red'    },
]

export function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('ALL')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchLogs = async () => {
    try {
      const r = await axios.get('/api/logs', { params: { limit: 500 } })
      const apiLogs = r.data.logs || []
      if (apiLogs.length === 0) {
        const eventsRes = await axios.get('/api/events', { params: { limit: 200 } })
        const events = eventsRes.data.events || []
        if (events.length > 0) {
          setLogs(events)
        } else {
          setLogs([])
        }
      } else {
        setLogs(apiLogs)
      }
    } catch { }
    setLoading(false)
  }

  useEffect(() => {
    fetchLogs()
    if (!autoRefresh) return
    const id = setInterval(fetchLogs, 5000)
    return () => clearInterval(id)
  }, [autoRefresh])

  const filtered = useMemo(() => {
    let items = logs
    if (filter !== 'ALL') items = items.filter(l => l.event === filter)
    if (search.trim()) {
      const q = search.toLowerCase()
      items = items.filter(l => JSON.stringify(l).toLowerCase().includes(q))
    }
    return items.reverse()
  }, [logs, filter, search])

  const scanCount = useMemo(() => {
    const orb = logs.filter(l => l.event === 'ORB_SCAN').length
    const vwap = logs.filter(l => l.event === 'RECLAIM_SCAN').length
    const entries = logs.filter(l => l.event === 'ENTRY').length
    const slmFills = logs.filter(l => l.event === 'SLM_EXECUTED').length
    const heartbeats = logs.filter(l => l.event === 'HEARTBEAT').length
    const riskBlocked = logs.filter(l => l.event === 'RISK_BLOCKED').length
    const scanCycles = logs.filter(l => l.event === 'SCAN_CYCLE').length
    const multiSignals = logs.filter(l => l.event === 'SCAN_CYCLE' && (l.signals_detected ?? 0) > 1).length
    const skipped = orb + vwap - entries
    return { orb, vwap, entries, skipped, slmFills, heartbeats, riskBlocked, scanCycles, multiSignals }
  }, [logs])

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan/10 flex items-center justify-center">
            <ScrollText size={18} className="text-cyan" />
          </div>
          <div>
            <h1 className="text-lg font-extrabold text-text1 tracking-tight">Bot Decision Logs</h1>
            <p className="text-[11px] text-text3">Why trades were taken, why signals were skipped — full transparency</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setAutoRefresh(!autoRefresh)}
            className={clsx('flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-semibold border transition-all',
              autoRefresh ? 'bg-green/8 border-green/20 text-green' : 'bg-surface border-line/20 text-text3')}>
            <Radio size={10} className={autoRefresh ? 'animate-pulse' : ''} /> {autoRefresh ? 'Live' : 'Paused'}
          </button>
          <button onClick={() => { setLoading(true); fetchLogs() }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-semibold bg-surface border border-line/20 text-text3 hover:text-text2 transition-all">
            <RefreshCw size={10} /> Refresh
          </button>
        </div>
      </motion.div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        {[
          { label: 'ORB Scans', value: scanCount.orb, color: 'amber', icon: Zap },
          { label: 'VWAP Scans', value: scanCount.vwap, color: 'cyan', icon: Radio },
          { label: 'Entries Taken', value: scanCount.entries, color: 'green', icon: ArrowUpRight },
          { label: 'Signals Skipped', value: scanCount.skipped, color: 'red', icon: XCircle },
          { label: 'Scan Cycles', value: scanCount.scanCycles, color: 'cyan', icon: Eye },
          { label: 'Multi-Signal', value: scanCount.multiSignals, color: 'green', icon: Zap },
          { label: 'Risk Blocked', value: scanCount.riskBlocked, color: 'red', icon: XCircle },
        ].map(({ label, value, color, icon: Icon }) => {
          const borderMap = { amber: 'border-l-amber', cyan: 'border-l-cyan', green: 'border-l-green', red: 'border-l-red' } as const
          const textMap = { amber: 'text-amber', cyan: 'text-cyan', green: 'text-green', red: 'text-red' } as const
          return (
          <motion.div key={label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            className={clsx('glass-card rounded-xl p-3.5 border-l-[2px]', borderMap[color as keyof typeof borderMap])}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[9px] font-bold tracking-[0.15em] uppercase text-text3">{label}</span>
              <Icon size={11} className={textMap[color as keyof typeof textMap]} />
            </div>
            <div className={clsx('text-xl font-extrabold font-mono stat-val', textMap[color as keyof typeof textMap])}>{value}</div>
          </motion.div>
        )})}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {EVENT_TYPES.map(et => {
          const activeMap = {
            text3: 'bg-text3/12 border-text3/25 text-text3',
            amber: 'bg-amber/12 border-amber/25 text-amber',
            cyan: 'bg-cyan/12 border-cyan/25 text-cyan',
            green: 'bg-green/12 border-green/25 text-green',
            accent: 'bg-accent/12 border-accent/25 text-accent',
            red: 'bg-red/12 border-red/25 text-red',
          } as const
          return (
          <button key={et.id} onClick={() => setFilter(et.id)}
            className={clsx('px-3 py-1.5 rounded-xl text-[11px] font-semibold border transition-all',
              filter === et.id ? activeMap[et.color as keyof typeof activeMap] :
              'bg-surface/50 border-line/20 text-text3 hover:text-text2')}>
            {et.label}
          </button>
        )})}
        <div className="relative ml-auto">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text3" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search logs..."
            className="bg-surface border border-line/30 rounded-xl pl-7 pr-3 py-1.5 text-[11px] text-text1 focus:border-accent/40 focus:outline-none w-48 transition-colors" />
        </div>
      </div>

      {/* Log entries */}
      {loading ? (
        <div className="glass-card rounded-2xl p-10 text-center">
          <Loader2 size={20} className="animate-spin text-accent mx-auto mb-2" />
          <p className="text-text3 text-[12px]">Loading bot logs...</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center">
          <ScrollText size={28} className="text-text3 mx-auto mb-3" />
          <p className="text-text1 font-bold text-lg">No Bot Logs Yet</p>
          <p className="text-text3 text-sm mt-2 max-w-md mx-auto">
            Logs appear when the trading bot is running during market hours (9:15 AM – 3:30 PM IST).
            Each scan, signal, entry, and exit is logged with full filter details showing
            <span className="text-green font-semibold"> why a trade was taken</span> or
            <span className="text-red font-semibold"> why it was skipped</span>.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-3 max-w-sm mx-auto text-left">
            {[
              { event: 'ORB_SCAN', desc: 'Every 5-min candle evaluated for breakout', color: 'text-amber' },
              { event: 'VWAP_SCAN', desc: 'VWAP cross detection with filter results', color: 'text-cyan' },
              { event: 'ENTRY', desc: 'Trade entry with symbol, price, SL & target', color: 'text-green' },
              { event: 'TRADE_CLOSED', desc: 'Exit with P&L, reason, and duration', color: 'text-accent' },
            ].map(({ event, desc, color }) => (
              <div key={event} className="bg-surface/50 rounded-xl p-3 border border-line/15">
                <div className={clsx('text-xs font-bold uppercase', color)}>{event}</div>
                <div className="text-xs text-text3 mt-1">{desc}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="divide-y divide-line/10 max-h-[calc(100vh-350px)] overflow-y-auto">
            {filtered.map((log, i) => {
              const isExp = expanded === i
              const isScan = log.event === 'ORB_SCAN' || log.event === 'RECLAIM_SCAN' || log.event === 'EMA_PULLBACK_SCAN' || log.event === 'MOMENTUM_SCAN'
              const isScanCycle = log.event === 'SCAN_CYCLE'
              const isEntry = log.event === 'ENTRY'
              const isTrade = log.event === 'TRADE_CLOSED'
              const isError = log.event === 'LOOP_ERROR'
              const isSlm = log.event === 'SLM_EXECUTED'
              const isHB = log.event === 'HEARTBEAT'
              const isRiskBlocked = log.event === 'RISK_BLOCKED'
              const isKiteAuth = log.event === 'KITE_AUTH'
              const isSystem = log.event === 'SYSTEM_READY'
              const passed = log.all_passed
              const filters = log.filters || {}
              const filterEntries = Object.entries(filters) as [string, boolean | FilterVal][]
              const isFilterPassed = (v: boolean | FilterVal): boolean => v === true || (v !== null && typeof v === 'object' && !!(v as FilterVal).passed)
              const passedCount = filterEntries.filter(([, v]) => isFilterPassed(v)).length

              return (
                <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i * 0.01, 0.3) }}
                  className={clsx('px-5 py-3 cursor-pointer transition-colors', isExp ? 'bg-card/50' : 'hover:bg-card/30')}
                  onClick={() => setExpanded(isExp ? null : i)}>

                  <div className="flex items-start gap-3">
                    {/* Event type indicator */}
                    <div className={clsx('w-8 h-8 rounded-lg flex items-center justify-center shrink-0 mt-0.5',
                      isScanCycle ? 'bg-accent/10' :
                      isHB ? 'bg-green/8' :
                      isSystem ? 'bg-cyan/10' :
                      isKiteAuth ? 'bg-accent/10' :
                      isRiskBlocked ? 'bg-red/10' :
                      isEntry ? 'bg-green/10' :
                      isTrade ? 'bg-accent/10' :
                      isSlm ? 'bg-red/10' :
                      isError ? 'bg-red/10' :
                      isScan && passed ? 'bg-green/10' :
                      isScan ? 'bg-amber/10' : 'bg-surface')}>
                      {isScanCycle ? <Eye size={14} className="text-accent" /> :
                       isHB ? <Radio size={14} className="text-green" /> :
                       isSystem ? <Zap size={14} className="text-cyan" /> :
                       isKiteAuth ? <Key size={14} className="text-accent" /> :
                       isRiskBlocked ? <XCircle size={14} className="text-red" /> :
                       isEntry ? <ArrowUpRight size={14} className="text-green" /> :
                       isTrade ? <CheckCircle2 size={14} className="text-accent" /> :
                       isSlm ? <AlertTriangle size={14} className="text-red" /> :
                       isError ? <AlertTriangle size={14} className="text-red" /> :
                       isScan && passed ? <CheckCircle2 size={14} className="text-green" /> :
                       <XCircle size={14} className="text-amber" />}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        {/* Event badge */}
                        <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider',
                          isHB ? 'bg-green/8 text-green' :
                          isSystem ? 'bg-cyan/10 text-cyan' :
                          isKiteAuth ? 'bg-accent/10 text-accent-l' :
                          isRiskBlocked ? 'bg-red/10 text-red' :
                          isEntry ? 'bg-green/10 text-green' :
                          isTrade ? 'bg-accent/10 text-accent-l' :
                          isSlm ? 'bg-red/10 text-red' :
                          isError ? 'bg-red/10 text-red' :
                          log.event === 'ORB_SCAN' ? 'bg-amber/10 text-amber' : 'bg-cyan/10 text-cyan')}>
                          {log.event.replace(/_/g, ' ')}
                        </span>

                        {/* Signal indicator */}
                        {isScan && (
                          <>
                            <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                              passed ? 'bg-green/10 text-green' : 'bg-red/8 text-text3')}>
                              {passed ? `SIGNAL: ${log.signal || '—'}` : 'NO SIGNAL'}
                            </span>
                            {log.confidence != null && (
                              <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold font-mono',
                                log.confidence >= 70 ? 'bg-green/10 text-green' : log.confidence >= 50 ? 'bg-amber/10 text-amber' : 'bg-surface text-text3')}>
                                conf={Math.round(log.confidence)}
                              </span>
                            )}
                            {log.regime && (
                              <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-surface text-text3">{log.regime}</span>
                            )}
                          </>
                        )}

                        {/* SCAN_CYCLE — aggregated results */}
                        {isScanCycle && (
                          <>
                            <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                              log.signals_detected > 0 ? 'bg-green/10 text-green' : 'bg-surface text-text3')}>
                              {log.signals_detected > 0 ? `${log.signals_detected} SIGNAL${log.signals_detected > 1 ? 'S' : ''}` : 'NO SIGNAL'}
                            </span>
                            <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-surface text-text3">
                              {log.strategies_evaluated} scanned · {log.regime} · {log.trend}
                            </span>
                            {log.conviction != null && (
                              <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold font-mono',
                                log.conviction >= 0.7 ? 'bg-green/10 text-green' : log.conviction >= 0.4 ? 'bg-amber/10 text-amber' : 'bg-surface text-text3')}>
                                conv={Math.round(log.conviction * 100)}%
                              </span>
                            )}
                            {log.candidates?.length > 0 && (
                              <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-accent/10 text-accent-l">
                                BEST: {log.candidates[0].strategy} ({log.candidates[0].signal}, conf={Math.round(log.candidates[0].confidence)})
                              </span>
                            )}
                          </>
                        )}

                        {isEntry && log.strategy && (
                          <>
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-accent/10 text-accent-l">
                              {log.strategy} · {log.signal}
                            </span>
                            {log.confidence != null && (
                              <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold font-mono',
                                log.confidence >= 70 ? 'bg-green/10 text-green' : log.confidence >= 50 ? 'bg-amber/10 text-amber' : 'bg-surface text-text3')}>
                                conf={Math.round(log.confidence)}
                              </span>
                            )}
                            {log.trend && (
                              <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-surface text-text3">{log.trend}</span>
                            )}
                            {log.risk_multiplier != null && (
                              <span className="px-1 py-0.5 rounded text-[8px] font-bold font-mono bg-surface text-text3">
                                risk×{log.risk_multiplier.toFixed(2)}
                              </span>
                            )}
                          </>
                        )}

                        {isTrade && (
                          <>
                            <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                              (log.net_pnl ?? 0) >= 0 ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                              {(log.net_pnl ?? 0) >= 0 ? '+' : ''}₹{(log.net_pnl ?? 0).toLocaleString('en-IN')} · {log.exit_reason}
                            </span>
                            {log.exit_reason === 'SL_HIT' && log.sl_slippage_pct != null && Math.abs(log.sl_slippage_pct) > 0.01 && (
                              <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                                Math.abs(log.sl_slippage_pct) > 1 ? 'bg-red/10 text-red' : 'bg-amber/10 text-amber')}>
                                SL slip {Math.abs(log.sl_slippage_pct).toFixed(1)}% (₹{Math.abs(log.sl_extra_loss ?? 0).toFixed(0)})
                              </span>
                            )}
                          </>
                        )}

                        {isSlm && (
                          <>
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red/10 text-red">
                              Trigger ₹{log.trigger_price?.toFixed(1)} → Fill ₹{log.fill_price?.toFixed(1)}
                            </span>
                            <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                              Math.abs(log.slm_slippage_pct ?? 0) > 1 ? 'bg-red/10 text-red' : 'bg-amber/10 text-amber')}>
                              {Math.abs(log.slm_slippage_pct ?? 0).toFixed(1)}% slip · Extra ₹{Math.abs(log.extra_loss_total ?? 0).toFixed(0)}
                            </span>
                          </>
                        )}

                        {isHB && (
                          <>
                            <span className={clsx('px-1.5 py-0.5 rounded text-[8px] font-bold',
                              log.market_status === 'OPEN' ? 'bg-green/10 text-green' :
                              log.market_status === 'PRE_MARKET' ? 'bg-amber/10 text-amber' :
                              'bg-surface text-text3')}>
                              {log.market_status ?? 'CLOSED'} · {log.state ?? 'IDLE'}
                            </span>
                            <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-surface text-text2">
                              {log.trades_today ?? 0}/{log.max_trades ?? 3} trades · ₹{(log.daily_pnl ?? 0) >= 0 ? '+' : ''}{(log.daily_pnl ?? 0).toFixed(0)}
                            </span>
                            <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                              (log.drawdown_pct ?? 0) > 10 ? 'bg-red/10 text-red' : (log.drawdown_pct ?? 0) > 5 ? 'bg-amber/10 text-amber' : 'bg-green/8 text-green')}>
                              DD {(log.drawdown_pct ?? 0).toFixed(1)}% · ₹{(log.current_capital ?? 0).toLocaleString('en-IN')}
                            </span>
                            {log.kite_connected != null && (
                              <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                                log.kite_connected ? 'bg-green/8 text-green' : 'bg-red/8 text-red')}>
                                Kite {log.kite_connected ? 'OK' : 'DOWN'}
                              </span>
                            )}
                            {log.nifty_price && (
                              <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-accent/8 text-accent-l">
                                NIFTY ₹{Number(log.nifty_price).toLocaleString('en-IN')}
                              </span>
                            )}
                          </>
                        )}

                        {isKiteAuth && (
                          <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold',
                            log.success === false ? 'bg-red/10 text-red' : 'bg-green/10 text-green')}>
                            {log.method || 'auth'} · {log.message || (log.success ? 'OK' : 'Failed')}
                          </span>
                        )}

                        {isSystem && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan/10 text-cyan">
                            {log.message || 'System event'} · ₹{(log.capital ?? 0).toLocaleString('en-IN')} · {log.paper_mode ? 'PAPER' : 'LIVE'}
                          </span>
                        )}

                        {isRiskBlocked && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red/10 text-red">
                            {log.reason || 'Risk gate blocked'}
                          </span>
                        )}

                        {isError && (
                          <span className="text-[10px] text-red truncate max-w-[300px]">{log.error}</span>
                        )}

                        {/* Filter mini-bar */}
                        {isScan && filterEntries.length > 0 && (
                          <div className="flex items-center gap-0.5 ml-auto">
                            {filterEntries.slice(0, 8).map(([k, v], fi) => {
                              const ok = isFilterPassed(v)
                              return <div key={fi} className={clsx('w-1 h-3 rounded-full', ok ? 'bg-green' : 'bg-red/50')} />
                            })}
                            <span className="text-[9px] font-mono text-text3 ml-1">{passedCount}/{filterEntries.length}</span>
                          </div>
                        )}
                      </div>

                      {/* Heartbeat thinking line */}
                      {isHB && log.thinking && !isExp && (
                        <div className="text-[10px] text-text2 mt-1 italic">
                          {log.thinking}
                          {log.regime && <span className="not-italic ml-2 text-text3">· Regime: {log.regime} · Trend: {log.trend_state ?? '—'}</span>}
                        </div>
                      )}

                      {/* Scan cycle summary */}
                      {isScanCycle && !isExp && log.scans?.length > 0 && (
                        <div className="text-[10px] text-text3 mt-1 flex items-center gap-1.5 flex-wrap">
                          {(log.scans as Array<{strategy: string; passed: boolean; confidence: number}>).map((s: {strategy: string; passed: boolean; confidence: number}, si: number) => (
                            <span key={si} className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                              s.passed ? 'bg-green/10 text-green' : 'bg-surface text-text3')}>
                              {s.strategy.replace(/_/g, ' ')} {s.passed ? '✓' : '✗'} ({Math.round(s.confidence)})
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Scan detail line */}
                      {isScan && !isExp && (
                        <div className="text-[10px] text-text3 mt-1 flex items-center gap-2 flex-wrap">
                          {!passed && filterEntries.length > 0 && (
                            <span>
                              Failed: {filterEntries
                                .filter(([, v]) => !isFilterPassed(v))
                                .slice(0, 3)
                                .map(([k]) => k.replace(/_/g, ' '))
                                .join(', ')}
                            </span>
                          )}
                        </div>
                      )}

                      {/* Entry detail */}
                      {isEntry && !isExp && (
                        <div className="text-[10px] text-text3 mt-1 flex items-center gap-1.5 flex-wrap">
                          <span>{log.symbol} · Entry ₹{log.fill_price?.toFixed(0)} · SL ₹{log.sl?.toFixed(0)} · Target ₹{log.target?.toFixed(0)}</span>
                          {log.vix && <span>· VIX {log.vix.toFixed(1)}</span>}
                          {log.entry_latency_ms != null && (
                            <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                              log.entry_latency_ms > 2000 ? 'bg-red/10 text-red' : log.entry_latency_ms > 500 ? 'bg-amber/10 text-amber' : 'bg-green/10 text-green')}>
                              {log.entry_latency_ms}ms
                            </span>
                          )}
                          {log.slippage_pct != null && (
                            <span className={clsx('px-1 py-0.5 rounded text-[8px] font-bold',
                              Math.abs(log.slippage_pct) > 1 ? 'bg-red/10 text-red' : 'bg-amber/10 text-amber')}>
                              slip {log.slippage_pct.toFixed(1)}%
                            </span>
                          )}
                          {log.order_type && (
                            <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-accent/10 text-accent-l">{log.order_type}</span>
                          )}
                        </div>
                      )}

                      {/* Timestamp */}
                      <div className="text-[9px] text-text3 font-mono mt-1 flex items-center gap-1">
                        <Clock size={8} />
                        {new Date(log.ts).toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', day: 'numeric', month: 'short' })}
                      </div>
                    </div>

                    <ChevronDown size={12} className={clsx('text-text3 transition-transform shrink-0 mt-1', isExp && 'rotate-180')} />
                  </div>

                  {/* Expanded details */}
                  <AnimatePresence>
                    {isExp && (
                      <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                        <div className="mt-3 pt-3 border-t border-line/15">

                          {/* Scan cycle expanded detail */}
                          {isScanCycle && log.candidates?.length > 0 && (
                            <div className="mb-3">
                              <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2">Signal Candidates (ranked by confidence)</div>
                              <div className="space-y-1.5">
                                {(log.candidates as Array<{strategy: string; signal: string; confidence: number}>).map((c: {strategy: string; signal: string; confidence: number}, ci: number) => (
                                  <div key={ci} className={clsx('flex items-center justify-between px-3 py-2 rounded-lg border',
                                    ci === 0 ? 'bg-green/5 border-green/20' : 'bg-surface/30 border-line/15')}>
                                    <div className="flex items-center gap-2">
                                      <span className={clsx('text-[10px] font-bold', ci === 0 ? 'text-green' : 'text-text3')}>{ci + 1}</span>
                                      <span className="text-[11px] font-bold text-text1">{c.strategy.replace(/_/g, ' ')}</span>
                                      <span className={clsx('px-1.5 py-0.5 rounded text-[9px] font-bold', c.signal === 'CALL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>{c.signal}</span>
                                      {ci === 0 && <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-green/10 text-green">SELECTED</span>}
                                    </div>
                                    <span className={clsx('text-sm font-bold font-mono', c.confidence >= 70 ? 'text-green' : c.confidence >= 50 ? 'text-amber' : 'text-text3')}>{Math.round(c.confidence)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Filter breakdown for scans */}
                          {isScan && filterEntries.length > 0 && (
                            <div className="mb-3">
                              <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2">Filter Breakdown — Why {passed ? 'Signal Fired' : 'Signal Skipped'}</div>
                              <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                                {filterEntries.map(([key, v]) => {
                                  const ok = isFilterPassed(v)
                                  const detail = (v !== null && typeof v === 'object') ? v as FilterVal : null
                                  return (
                                    <div key={key} className={clsx('flex items-center gap-2 px-2 py-1.5 rounded-lg border text-[10px]',
                                      ok ? 'bg-green/5 border-green/15 text-green' : 'bg-red/5 border-red/12 text-red-l/70')}>
                                      {ok ? <CheckCircle2 size={10} /> : <XCircle size={10} />}
                                      <span className="capitalize truncate">{key.replace(/_/g, ' ')}</span>
                                      {detail?.value !== undefined && (
                                        <span className="ml-auto font-mono text-[9px] text-text3">
                                          {typeof detail.value === 'number' ? detail.value.toFixed(1) : String(detail.value)}
                                        </span>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            </div>
                          )}

                          {/* Diagnostic checks for SYSTEM_READY */}
                          {isSystem && log.checks && Array.isArray(log.checks) && (
                            <div className="mb-3">
                              <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2">
                                Startup Diagnostics — {log.checks_passed ?? 0} passed, {log.checks_warnings ?? 0} warn, {log.checks_failed ?? 0} fail
                              </div>
                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                                {(log.checks as Array<{name: string; status: string; detail: string}>).map((c: {name: string; status: string; detail: string}, ci: number) => (
                                  <div key={ci} className={clsx('flex items-center gap-2 px-2 py-1 rounded-lg border text-[10px]',
                                    c.status === 'PASS' ? 'bg-green/5 border-green/15 text-green' :
                                    c.status === 'WARN' ? 'bg-amber/5 border-amber/15 text-amber' :
                                    'bg-red/5 border-red/12 text-red')}>
                                    {c.status === 'PASS' ? <CheckCircle2 size={10} /> : c.status === 'WARN' ? <AlertTriangle size={10} /> : <XCircle size={10} />}
                                    <span className="truncate">{c.name}</span>
                                    {c.detail && <span className="ml-auto font-mono text-[9px] text-text3 truncate max-w-[150px]">{c.detail}</span>}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Raw data */}
                          <details className="group">
                            <summary className="text-[10px] text-text3 cursor-pointer hover:text-text2 flex items-center gap-1">
                              <Eye size={10} /> Raw data
                            </summary>
                            <pre className="mt-2 text-[9px] font-mono text-text3 bg-surface/50 rounded-lg p-3 overflow-x-auto max-h-[200px]">
                              {JSON.stringify(log, null, 2)}
                            </pre>
                          </details>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
