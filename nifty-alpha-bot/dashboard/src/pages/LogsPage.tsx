/**
 * LogsPage — live event browser.
 *   Left: fixed filter sidebar  Right: scrollable timeline
 *   Every event is expandable with full structured data.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  ScrollText, Search, CheckCircle2, XCircle, AlertTriangle,
  Zap, ChevronDown, RefreshCw, Loader2, Eye, EyeOff,
  Radio, TrendingUp, TrendingDown, Info, Clock, Shield,
  Activity, Layers, BarChart2, XOctagon,
} from 'lucide-react'

/* ── Types ───────────────────────────────────────────────────────*/
interface FilterVal { passed?: boolean; value?: number | string; detail?: string }
interface LogEntry {
  ts: string; event: string
  filters?: Record<string, boolean | FilterVal>
  [key: string]: unknown
}

/* ── Event registry ──────────────────────────────────────────────*/
const META: Record<string, { label: string; color: string; dot: string; icon: typeof Zap }> = {
  HEARTBEAT:           { label: 'Heartbeat',      color: 'text-text3',  dot: 'bg-text3/30',   icon: Activity   },
  DAILY_ADAPTIVE_SCAN: { label: 'Daily Scan',     color: 'text-accent', dot: 'bg-accent',     icon: BarChart2  },
  DAILY_REGIME:        { label: 'Regime Lock',    color: 'text-cyan',   dot: 'bg-cyan',       icon: Layers     },
  TREND_DETECTED:      { label: 'Trend',          color: 'text-green',  dot: 'bg-green',      icon: TrendingUp },
  TREND_SHIFTED:       { label: 'Trend Shift',    color: 'text-cyan',   dot: 'bg-cyan/70',    icon: TrendingUp },
  REGIME_DETECTED:     { label: 'Regime',         color: 'text-cyan',   dot: 'bg-cyan/60',    icon: Layers     },
  ORB_SCAN:            { label: 'ORB',            color: 'text-amber',  dot: 'bg-amber',      icon: Zap        },
  EMA_PULLBACK_SCAN:   { label: 'EMA Pullback',   color: 'text-accent', dot: 'bg-accent/70',  icon: Zap        },
  MOMENTUM_SCAN:       { label: 'Momentum',       color: 'text-green',  dot: 'bg-green/70',   icon: Zap        },
  RECLAIM_SCAN:        { label: 'VWAP Reclaim',   color: 'text-cyan',   dot: 'bg-cyan/60',    icon: Zap        },
  SCAN_CYCLE:          { label: 'Scan Cycle',     color: 'text-text2',  dot: 'bg-text2/25',   icon: RefreshCw  },
  ENTRY:               { label: 'ENTRY',          color: 'text-green',  dot: 'bg-green',      icon: TrendingUp },
  TRADE_CLOSED:        { label: 'EXIT',           color: 'text-amber',  dot: 'bg-amber',      icon: TrendingDown},
  EXIT:                { label: 'EXIT',           color: 'text-amber',  dot: 'bg-amber',      icon: TrendingDown},
  RISK_BLOCKED:        { label: 'Risk Block',     color: 'text-red',    dot: 'bg-red',        icon: Shield     },
  SLM_EXECUTED:        { label: 'SL-M Hit',       color: 'text-red',    dot: 'bg-red',        icon: XCircle    },
  BROKER_SYNC_CLOSED:  { label: 'Broker Sync',    color: 'text-amber',  dot: 'bg-amber/70',   icon: RefreshCw  },
  KITE_AUTH:           { label: 'Kite Auth',      color: 'text-green',  dot: 'bg-green',      icon: CheckCircle2},
  RUNTIME_OVERRIDE:    { label: 'Override',       color: 'text-accent', dot: 'bg-accent',     icon: Zap        },
  MANUAL_SIGNAL:       { label: 'Manual Signal',  color: 'text-accent', dot: 'bg-accent',     icon: Zap        },
  EMERGENCY_STOP:      { label: 'E-STOP',         color: 'text-red',    dot: 'bg-red',        icon: XOctagon   },
  BOT_PAUSED:          { label: 'Bot Paused',     color: 'text-amber',  dot: 'bg-amber',      icon: AlertTriangle},
  BOT_RESUMED:         { label: 'Bot Resumed',    color: 'text-green',  dot: 'bg-green',      icon: CheckCircle2},
  LOOP_ERROR:          { label: 'Error',          color: 'text-red',    dot: 'bg-red',        icon: AlertTriangle},
  FORCE_CLOSE_REQUESTED:{ label: 'Force Close',   color: 'text-red',    dot: 'bg-red',        icon: XCircle    },
}
const DEFAULT_META = { label: '', color: 'text-text2', dot: 'bg-text2/25', icon: Info }

function getMeta(ev: string) {
  if (META[ev]) return META[ev]
  // Partial match
  for (const [k, v] of Object.entries(META)) {
    if (ev.startsWith(k) || k.startsWith(ev)) return v
  }
  return { ...DEFAULT_META, label: ev.replace(/_/g,' ') }
}

/* ── Tabs ────────────────────────────────────────────────────────*/
const TABS = [
  { id: 'all',       label: 'All',       fn: (_: LogEntry) => true },
  { id: 'trades',    label: '📈 Trades',  fn: (e: LogEntry) => ['ENTRY','EXIT','TRADE_CLOSED','SLM_EXECUTED'].some(k => (e.event??'').includes(k)) },
  { id: 'decisions', label: '🧠 Decide',  fn: (e: LogEntry) => ['DAILY_REGIME','DAILY_ADAPTIVE','TREND','REGIME','SIGNAL','CONFIDENCE'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
  { id: 'errors',    label: '⚠ Errors',  fn: (e: LogEntry) => ['ERROR','EXCEPTION','FAILED','LOOP_ERROR','CRITICAL'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
  { id: 'scans',     label: '🔍 Scans',   fn: (e: LogEntry) => (e.event??'').includes('SCAN') || (e.event??'').includes('RECLAIM') },
  { id: 'skipped',   label: '⏭ Skipped', fn: (e: LogEntry) => ['SKIP','RISK_BLOCK','OVEREXTENDED','LOW_QUALITY'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
] as const
type TabId = typeof TABS[number]['id']

/* ── Filter pills ────────────────────────────────────────────────*/
function FilterPills({ filters }: { filters: Record<string, boolean | FilterVal> }) {
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {Object.entries(filters).map(([k, v]) => {
        const ok   = v === true  || (v as FilterVal)?.passed === true
        const fail = v === false || (v as FilterVal)?.passed === false
        const fv   = typeof v === 'object' ? v as FilterVal : null
        return (
          <span key={k} className={clsx(
            'flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded border font-mono',
            ok ? 'bg-green/8 border-green/20 text-green' : fail ? 'bg-red/8 border-red/20 text-red/70' : 'bg-surface border-line/25 text-text3'
          )}>
            {ok ? <CheckCircle2 size={7} /> : fail ? <XCircle size={7} /> : <div className="w-1 h-1 rounded-full bg-text3/40" />}
            {k.replace(/_/g,' ')}
            {fv?.value != null && <span className="text-cyan/80">={typeof fv.value === 'number' ? fv.value.toFixed(2) : fv.value}</span>}
            {fv?.detail && <span className="text-text3 max-w-[100px] truncate">({fv.detail})</span>}
          </span>
        )
      })}
    </div>
  )
}

/* ── Log entry ───────────────────────────────────────────────────*/
function LogRow({ entry, idx }: { entry: LogEntry; idx: number }) {
  const [open, setOpen] = useState(false)
  const m  = getMeta(entry.event ?? '')
  const Icon = m.icon

  const ts = entry.ts
    ? new Date(entry.ts).toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false, timeZone:'Asia/Kolkata' })
    : ''
  const date = entry.ts
    ? new Date(entry.ts).toLocaleDateString('en-IN', { day:'2-digit', month:'short', timeZone:'Asia/Kolkata' })
    : ''

  const hasFilters = !!entry.filters && Object.keys(entry.filters).length > 0
  const pnlRaw     = entry.net_pnl ?? entry.pnl ?? entry.daily_pnl
  const pnl        = pnlRaw != null && (typeof pnlRaw === 'number' || typeof pnlRaw === 'string') ? Number(pnlRaw) : null
  const msgFields  = ['message','reason','error','detail','status','thinking']
  const msg        = msgFields.map(f => entry[f]).filter((v): v is string => typeof v === 'string' && v.length > 0).join(' · ')

  // For structured fields summary (exclude system/UI-rendered fields)
  const SKIP_KEYS = new Set(['ts','event','filters','message','reason','error','detail','status','thinking','pnl','net_pnl','daily_pnl','symbol','strategy','regime','direction','state'])
  const structFields = Object.entries(entry).filter(([k]) => !SKIP_KEYS.has(k)).slice(0, 8)

  return (
    <motion.div
      initial={{ opacity:0, x:-4 }} animate={{ opacity:1, x:0 }}
      transition={{ delay: Math.min(idx, 30) * 0.008 }}
      className="flex gap-3 py-2.5 border-b border-line/10 last:border-0 group hover:bg-surface/20 transition-colors rounded-lg px-1"
    >
      {/* Timeline dot + line */}
      <div className="flex flex-col items-center pt-1 shrink-0 w-4">
        <div className={clsx('w-2 h-2 rounded-full shrink-0 ring-2 ring-bg', m.dot)} />
        <div className="flex-1 w-px bg-line/15 mt-1" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Top row */}
        <div className="flex flex-wrap items-center gap-2 mb-0.5">
          <Icon size={10} className={clsx('shrink-0', m.color)} />
          <span className={clsx('text-[10px] font-black uppercase tracking-wide', m.color)}>
            {m.label || entry.event}
          </span>
          {pnl != null && (
            <span className={clsx('text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border',
              pnl >= 0 ? 'text-green bg-green/8 border-green/20' : 'text-red bg-red/8 border-red/20')}>
              {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toFixed(0)}
            </span>
          )}
          {(entry.state as string) && (
            <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-surface border border-line/25 text-text3">
              {typeof entry.state === 'string' ? entry.state : ''}
            </span>
          )}
          <span className="ml-auto text-[9px] font-mono text-text3/60 shrink-0 flex items-center gap-1">
            <Clock size={8} /> {date} {ts}
          </span>
        </div>

        {/* Main message */}
        {msg && (
          <p className="text-[11px] text-text2 leading-relaxed mb-1">{msg}</p>
        )}

        {/* Strategy / symbol quick info */}
        {!!(entry.symbol || entry.strategy || entry.regime || entry.direction) && (
          <div className="flex flex-wrap gap-1.5 mb-1">
            {typeof entry.symbol   === 'string' && entry.symbol   && <span className="text-[9px] font-mono bg-accent/8 text-accent px-1.5 py-0.5 rounded border border-accent/20">{entry.symbol}</span>}
            {typeof entry.strategy === 'string' && entry.strategy && <span className="text-[9px] font-mono bg-surface text-text2 px-1.5 py-0.5 rounded border border-line/25">{entry.strategy}</span>}
            {typeof entry.regime   === 'string' && entry.regime   && <span className="text-[9px] font-mono bg-cyan/8 text-cyan px-1.5 py-0.5 rounded border border-cyan/20">{entry.regime}</span>}
            {typeof entry.direction === 'string' && entry.direction && (
              <span className={clsx('text-[9px] font-mono px-1.5 py-0.5 rounded border',
                entry.direction.includes('CE') ? 'bg-green/8 text-green border-green/20' : 'bg-red/8 text-red border-red/20')}>
                {entry.direction}
              </span>
            )}
          </div>
        )}

        {/* Filter pills (always shown when present) */}
        {hasFilters && <FilterPills filters={entry.filters!} />}

        {/* Expand button for raw data */}
        <button
          onClick={() => setOpen(o => !o)}
          className="mt-1.5 flex items-center gap-1 text-[9px] text-text3 hover:text-accent transition-colors">
          <ChevronDown size={9} className={clsx('transition-transform', open && 'rotate-180')} />
          {open ? 'hide details' : 'show details'}
        </button>

        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ height:0, opacity:0 }} animate={{ height:'auto', opacity:1 }}
              exit={{ height:0, opacity:0 }}
              className="overflow-hidden"
            >
              {/* Structured key/value pairs */}
              {structFields.length > 0 && (
                <div className="mt-1.5 grid grid-cols-2 gap-1">
                  {structFields.map(([k, v]) => (
                    <div key={k} className="flex items-start gap-1.5 text-[9px] bg-surface/50 rounded px-2 py-1">
                      <span className="text-text3 shrink-0 font-mono">{k}:</span>
                      <span className="text-text2 font-mono truncate">
                        {v == null ? '—' : typeof v === 'object' ? JSON.stringify(v).slice(0,60) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {/* Raw JSON */}
              <details className="mt-1.5">
                <summary className="text-[9px] text-text3 cursor-pointer hover:text-accent">raw JSON</summary>
                <pre className="text-[8px] font-mono text-text3 bg-bg/80 rounded-lg p-2 mt-1 overflow-x-auto max-h-40 overflow-y-auto">
                  {JSON.stringify(entry, null, 2)}
                </pre>
              </details>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

/* ── Main page ───────────────────────────────────────────────────*/
export function LogsPage() {
  const [logs, setLogs]               = useState<LogEntry[]>([])
  const [loading, setLoading]         = useState(true)
  const [search, setSearch]           = useState('')
  const [tab, setTab]                 = useState<TabId>('all')
  const [showHB, setShowHB]           = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [limit, setLimit]             = useState(300)
  const listRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const r = await axios.get('/api/logs', { params: { limit: 600 } })
      const raw: LogEntry[] = r.data?.logs ?? r.data ?? []
      setLogs(raw.slice().reverse())
    } catch { /* keep stale data on error */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    load()
    if (!autoRefresh) return
    const id = setInterval(load, 8_000)
    return () => clearInterval(id)
  }, [autoRefresh, load])

  const tabFn = useMemo(() => TABS.find(t => t.id === tab)?.fn ?? (() => true), [tab])

  const filtered = useMemo(() => {
    let out = logs
    if (!showHB) out = out.filter(e => e.event !== 'HEARTBEAT')
    out = out.filter(tabFn)
    if (search.trim()) {
      const q = search.toLowerCase()
      out = out.filter(e => JSON.stringify(e).toLowerCase().includes(q))
    }
    return out
  }, [logs, showHB, tab, search, tabFn])

  const counts = useMemo(() => ({
    trades:    logs.filter(e => ['ENTRY','TRADE_CLOSED','EXIT'].some(k => (e.event??'').includes(k))).length,
    decisions: logs.filter(e => ['DAILY_REGIME','TREND','SIGNAL'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
    errors:    logs.filter(e => ['ERROR','FAILED','LOOP_ERROR'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
    scans:     logs.filter(e => (e.event??'').includes('SCAN') || (e.event??'').includes('RECLAIM')).length,
    skipped:   logs.filter(e => ['SKIP','RISK_BLOCK'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
  }), [logs])

  const visible = filtered.slice(0, limit)

  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden">

      {/* ── Left sidebar: filters ─────────────── */}
      <div className="w-48 shrink-0 border-r border-line/20 flex flex-col bg-bg/60 overflow-y-auto">
        <div className="p-3 border-b border-line/20">
          <div className="flex items-center gap-2">
            <ScrollText size={14} className="text-accent" />
            <span className="text-[12px] font-bold text-text1">Event Log</span>
          </div>
          <p className="text-[10px] text-text3 mt-0.5">{logs.length} events</p>
        </div>

        {/* Tabs */}
        <div className="p-2 space-y-1">
          {TABS.map(t => {
            const cnt = t.id !== 'all' ? counts[t.id as keyof typeof counts] : filtered.length
            return (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={clsx(
                  'w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all',
                  tab === t.id
                    ? 'bg-accent/15 text-accent border border-accent/25'
                    : 'text-text3 hover:text-text2 hover:bg-surface/50'
                )}>
                <span>{t.label}</span>
                {cnt > 0 && (
                  <span className={clsx('text-[9px] font-bold font-mono px-1.5 rounded',
                    tab === t.id ? 'bg-accent/20 text-accent' : 'bg-surface text-text3')}>
                    {cnt}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        <div className="p-2 border-t border-line/20 space-y-2 mt-auto">
          <button onClick={() => setShowHB(s => !s)}
            className={clsx('w-full flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-bold transition-all',
              showHB ? 'bg-accent/10 text-accent border-accent/25' : 'text-text3 border-line/30 hover:border-accent/30')}>
            {showHB ? <Eye size={10} /> : <EyeOff size={10} />} Heartbeats
          </button>
          <button onClick={() => setAutoRefresh(a => !a)}
            className={clsx('w-full flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-bold transition-all',
              autoRefresh ? 'bg-green/10 text-green border-green/25' : 'text-text3 border-line/30')}>
            <Radio size={10} /> {autoRefresh ? 'Live' : 'Paused'}
          </button>
          <button onClick={load} disabled={loading}
            className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-line/30 text-[10px] text-text3 hover:text-accent hover:border-accent/30 transition-all">
            {loading ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
            Refresh
          </button>
        </div>
      </div>

      {/* ── Right: timeline ───────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Search bar */}
        <div className="px-4 py-3 border-b border-line/20 flex items-center gap-3">
          <div className="relative flex-1">
            <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text3" />
            <input
              value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search events, symbols, strategies, reasons..."
              className="w-full bg-surface/60 border border-line/30 rounded-xl pl-8 pr-4 py-2 text-[12px] text-text1 placeholder:text-text3/60 focus:outline-none focus:border-accent/40 transition-colors"
            />
          </div>
          <span className="text-[10px] text-text3 font-mono shrink-0">
            {visible.length}/{filtered.length} shown
          </span>
        </div>

        {/* Scrollable event list */}
        <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-2">
          {loading && filtered.length === 0 && (
            <div className="flex items-center justify-center py-20 gap-3 text-text3">
              <Loader2 size={18} className="animate-spin text-accent" /> Loading events...
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="text-center py-20 text-text3 text-sm">
              No events match this filter.
            </div>
          )}

          {visible.map((e, i) => (
            <LogRow key={`${e.ts}-${i}`} entry={e} idx={i} />
          ))}

          {filtered.length > limit && (
            <button
              onClick={() => setLimit(l => l + 200)}
              className="w-full py-3 text-[11px] text-accent hover:text-accent/80 font-bold border-t border-line/20 mt-2 transition-colors">
              Load 200 more ({filtered.length - limit} remaining)
            </button>
          )}
        </div>
      </div>
    </div>
  )
}