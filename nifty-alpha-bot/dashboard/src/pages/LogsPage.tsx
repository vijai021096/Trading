/**
 * LogsPage — live event browser with smart filtering, search,
 * expandable detail, and color-coded timeline.
 */
import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  ScrollText, Filter, Search, CheckCircle2, XCircle, AlertTriangle,
  Clock, Zap, ChevronDown, RefreshCw, Loader2, Eye, EyeOff,
  ArrowUpRight, ArrowDownRight, Radio, Info,
} from 'lucide-react'

/* ── Types ──────────────────────────────────────────────────────── */
interface FilterVal { passed?: boolean; value?: number | string; detail?: string }
interface LogEntry {
  ts: string; event: string
  filters?: Record<string, boolean | FilterVal>
  all_passed?: boolean
  [key: string]: any
}

/* ── Event type registry ────────────────────────────────────────── */
const EVENT_META: Record<string, { label: string; color: string; dot: string }> = {
  HEARTBEAT:           { label: 'Heartbeat',     color: 'text-text3',   dot: 'bg-text3/40'   },
  DAILY_ADAPTIVE_SCAN: { label: 'Daily Scan',    color: 'text-accent',  dot: 'bg-accent'     },
  DAILY_REGIME:        { label: 'Regime Lock',   color: 'text-cyan',    dot: 'bg-cyan'       },
  TREND_DETECTED:      { label: 'Trend',         color: 'text-green',   dot: 'bg-green'      },
  REGIME_DETECTED:     { label: 'Regime',        color: 'text-cyan',    dot: 'bg-cyan/70'    },
  ORB_SCAN:            { label: 'ORB',           color: 'text-amber',   dot: 'bg-amber'      },
  EMA_PULLBACK_SCAN:   { label: 'EMA Pullback',  color: 'text-accent',  dot: 'bg-accent/70'  },
  MOMENTUM_SCAN:       { label: 'Momentum',      color: 'text-green',   dot: 'bg-green/70'   },
  RECLAIM_SCAN:        { label: 'VWAP Reclaim',  color: 'text-cyan',    dot: 'bg-cyan/60'    },
  SCAN_CYCLE:          { label: 'Scan',          color: 'text-text2',   dot: 'bg-text2/30'   },
  ENTRY:               { label: 'Entry ↗',       color: 'text-green',   dot: 'bg-green'      },
  TRADE_CLOSED:        { label: 'Exit ↘',        color: 'text-accent',  dot: 'bg-accent'     },
  RISK_BLOCKED:        { label: 'Risk Block',    color: 'text-red-l',   dot: 'bg-red'        },
  SLM_EXECUTED:        { label: 'SL-M Hit',      color: 'text-red-l',   dot: 'bg-red'        },
  BROKER_SYNC_CLOSED:  { label: 'Broker Sync',   color: 'text-amber',   dot: 'bg-amber/70'   },
  KITE_AUTH:           { label: 'Kite Auth',     color: 'text-green',   dot: 'bg-green'      },
  RUNTIME_OVERRIDE:    { label: 'Override',      color: 'text-accent',  dot: 'bg-accent'     },
  EMERGENCY_STOP:      { label: 'E-STOP',        color: 'text-red-l',   dot: 'bg-red'        },
  LOOP_ERROR:          { label: 'Error',         color: 'text-red-l',   dot: 'bg-red'        },
}

function meta(ev: string) {
  for (const [k, v] of Object.entries(EVENT_META)) {
    if (ev.includes(k) || k.includes(ev)) return v
  }
  return { label: ev.replace(/_/g, ' '), color: 'text-text2', dot: 'bg-text2/30' }
}

const TABS = [
  { id: 'all',       label: 'All',       match: () => true },
  { id: 'trades',    label: 'Trades',    match: (e: LogEntry) => ['TRADE_CLOSED','ENTRY','EXIT'].some(k => e.event?.includes(k)) },
  { id: 'decisions', label: 'Decisions', match: (e: LogEntry) => ['DAILY_REGIME','DAILY_ADAPTIVE','TREND','MOMENTUM','SIGNAL','CONFIDENCE','BEST_SIGNAL'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
  { id: 'errors',    label: 'Errors',    match: (e: LogEntry) => ['ERROR','EXCEPTION','FAILED','WARNING','CRITICAL'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
  { id: 'skipped',   label: 'Skipped',   match: (e: LogEntry) => ['SKIP','LOW_QUALITY','OVEREXTENDED','RISK_BLOCKED'].some(k => JSON.stringify(e).toUpperCase().includes(k)) },
] as const

type TabId = typeof TABS[number]['id']

/* ── Filter quality pills ───────────────────────────────────────── */
function FilterPills({ filters }: { filters: Record<string, boolean | FilterVal> }) {
  const entries = Object.entries(filters)
  const passed  = entries.filter(([, v]) => v === true || (v as FilterVal)?.passed === true)
  const failed  = entries.filter(([, v]) => v === false || (v as FilterVal)?.passed === false)
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {entries.map(([k, v]) => {
        const ok   = v === true || (v as FilterVal)?.passed === true
        const fail = v === false || (v as FilterVal)?.passed === false
        const fv   = typeof v === 'object' ? v as FilterVal : null
        return (
          <span key={k} className={clsx(
            'flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded border',
            ok ? 'bg-green/8 border-green/20 text-green' : fail ? 'bg-red/8 border-red/20 text-red-l/70' : 'bg-surface border-line/25 text-text3'
          )}>
            {ok ? <CheckCircle2 size={8} /> : fail ? <XCircle size={8} /> : <div className="w-1.5 h-1.5 rounded-full bg-text3/40" />}
            <span className="capitalize">{k.replace(/_/g, ' ')}</span>
            {fv?.value != null && <span className="font-mono text-cyan/70">={typeof fv.value === 'number' ? fv.value.toFixed(2) : fv.value}</span>}
          </span>
        )
      })}
    </div>
  )
}

/* ── Log entry row ──────────────────────────────────────────────── */
function LogRow({ entry, idx }: { entry: LogEntry; idx: number }) {
  const [open, setOpen] = useState(false)
  const m = meta(entry.event ?? '')
  const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : ''
  const date = entry.ts ? new Date(entry.ts).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : ''
  const hasFilters = !!entry.filters && Object.keys(entry.filters).length > 0
  const pnl  = entry.pnl ?? entry.net_pnl
  const state = entry.state
  const thinking = entry.thinking
  const msgFields = ['message','reason','error','detail','status','trade_id']
  const msg  = msgFields.map(f => entry[f]).filter(Boolean).join(' · ')

  return (
    <motion.div
      initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }}
      transition={{ delay: Math.min(idx, 20) * 0.015 }}
      className="flex gap-3 py-3 border-b border-line/10 last:border-0 group"
    >
      {/* Timeline dot */}
      <div className="flex flex-col items-center pt-1 shrink-0">
        <div className={clsx('w-2 h-2 rounded-full shrink-0', m.dot)} />
        <div className="flex-1 w-px bg-line/20 mt-1" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={clsx('text-[10px] font-black uppercase tracking-wider', m.color)}>
            {m.label}
          </span>
          {state && (
            <span className="text-[9px] px-1.5 py-0.5 rounded border border-line/25 bg-surface text-text3 font-mono">
              {state}
            </span>
          )}
          {pnl != null && (
            <span className={clsx('text-[10px] font-mono font-bold', pnl >= 0 ? 'text-green' : 'text-red-l')}>
              {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toFixed(0)}
            </span>
          )}
          <span className="ml-auto font-mono text-[10px] text-text3">
            {date} {ts}
          </span>
        </div>

        {/* Main message */}
        {msg && <p className="text-[11px] text-text2 mt-0.5 leading-relaxed">{msg}</p>}

        {/* Bot thinking */}
        {thinking && <p className="text-[10px] text-text3 mt-0.5 italic leading-relaxed">{thinking}</p>}

        {/* Filter pills */}
        {hasFilters && <FilterPills filters={entry.filters!} />}

        {/* Expandable raw JSON */}
        {!hasFilters && (
          <div className="mt-1">
            <button onClick={() => setOpen(o => !o)}
              className="text-[9px] text-text3 hover:text-accent flex items-center gap-1 transition-colors">
              {open ? <ChevronDown size={9} /> : <ChevronDown size={9} className="-rotate-90" />}
              {open ? 'hide' : 'details'}
            </button>
            <AnimatePresence>
              {open && (
                <motion.pre
                  initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="overflow-hidden text-[9px] font-mono text-text3 bg-bg/80 rounded-lg p-2 mt-1 overflow-x-auto max-h-48"
                >
                  {JSON.stringify(entry, null, 2)}
                </motion.pre>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </motion.div>
  )
}

/* ── Main export ─────────────────────────────────────────────────── */
export function LogsPage() {
  const [logs, setLogs]         = useState<LogEntry[]>([])
  const [loading, setLoading]   = useState(true)
  const [search, setSearch]     = useState('')
  const [tab, setTab]           = useState<TabId>('all')
  const [eventFilter, setEventFilter] = useState('ALL')
  const [showHB, setShowHB]     = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const load = async () => {
    try {
      const r = await axios.get('/api/logs', { params: { limit: 500 } })
      setLogs((r.data?.logs ?? r.data ?? []).reverse())
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    if (!autoRefresh) return
    const id = setInterval(load, 8_000)
    return () => clearInterval(id)
  }, [autoRefresh])

  const tabFn = useMemo(() => TABS.find(t => t.id === tab)?.match ?? (() => true), [tab])

  const filtered = useMemo(() => {
    let out = logs
    if (!showHB) out = out.filter(e => e.event !== 'HEARTBEAT')
    if (eventFilter !== 'ALL') out = out.filter(e => (e.event ?? '').includes(eventFilter))
    out = out.filter(tabFn)
    if (search.trim()) {
      const q = search.toLowerCase()
      out = out.filter(e => JSON.stringify(e).toLowerCase().includes(q))
    }
    return out
  }, [logs, showHB, eventFilter, tab, search, tabFn])

  const counts = useMemo(() => ({
    trades:    logs.filter(e => ['TRADE_CLOSED','ENTRY'].some(k => e.event?.includes(k))).length,
    decisions: logs.filter(e => ['DAILY_REGIME','TREND','SIGNAL'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
    errors:    logs.filter(e => ['ERROR','FAILED'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
    skipped:   logs.filter(e => ['SKIP','RISK_BLOCKED'].some(k => JSON.stringify(e).toUpperCase().includes(k))).length,
  }), [logs])

  return (
    <div className="flex-1 overflow-y-auto p-3 lg:p-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center">
            <ScrollText size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-lg font-black text-text1">Event Log</h1>
            <p className="text-[11px] text-text3">{logs.length} events loaded</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowHB(s => !s)}
            className={clsx('flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-bold transition-all',
              showHB ? 'bg-accent/10 text-accent border-accent/25' : 'text-text3 border-line/30 hover:border-accent/30')}>
            {showHB ? <Eye size={11} /> : <EyeOff size={11} />} Heartbeats
          </button>
          <button onClick={() => setAutoRefresh(a => !a)}
            className={clsx('flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[10px] font-bold transition-all',
              autoRefresh ? 'bg-green/10 text-green border-green/25' : 'text-text3 border-line/30 hover:border-accent/30')}>
            <Radio size={11} /> {autoRefresh ? 'Live' : 'Paused'}
          </button>
          <button onClick={load} disabled={loading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-line/30 text-[10px] text-text3 hover:text-accent hover:border-accent/30 transition-all">
            {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-surface/70 rounded-xl p-0.5 border border-line/30 mb-4 w-fit">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={clsx(
              'relative px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all',
              tab === t.id ? 'text-bg' : 'text-text3 hover:text-text2'
            )}>
            {tab === t.id && (
              <motion.div layoutId="logs-tab"
                className="absolute inset-0 rounded-lg bg-accent"
                transition={{ type: 'spring', stiffness: 500, damping: 35 }} />
            )}
            <span className="relative z-10">
              {t.label}
              {t.id !== 'all' && counts[t.id as keyof typeof counts] > 0 && (
                <span className="ml-1 text-[9px] opacity-70">{counts[t.id as keyof typeof counts]}</span>
              )}
            </span>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text3" />
        <input
          value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search events, strategies, reasons..."
          className="w-full bg-surface/60 border border-line/30 rounded-xl pl-9 pr-4 py-2.5 text-sm text-text1 placeholder:text-text3 focus:outline-none focus:border-accent/40 transition-colors"
        />
      </div>

      {/* Event feed */}
      <div className="glass-card rounded-2xl p-4">
        {loading && filtered.length === 0 ? (
          <div className="flex items-center justify-center py-12 gap-3 text-text3">
            <Loader2 size={18} className="animate-spin text-accent" /> Loading events...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-text3 text-sm">No events match this filter.</div>
        ) : (
          <div>
            <div className="text-[10px] text-text3 mb-3 font-mono">
              Showing {filtered.length} of {logs.length} events
            </div>
            {filtered.slice(0, 200).map((e, i) => (
              <LogRow key={`${e.ts}-${i}`} entry={e} idx={i} />
            ))}
            {filtered.length > 200 && (
              <p className="text-[10px] text-text3 text-center pt-3">Showing first 200 — refine filter to see more</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}