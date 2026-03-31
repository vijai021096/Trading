/**
 * TradePlan — today's planned trade legs from /api/daily-watch.
 * Shows: strategy, direction, lots, SL%, target%, filter quality, R:R.
 */
import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Target, TrendingUp, TrendingDown, CheckCircle2, XCircle,
  ChevronDown, ChevronRight, Layers, Clock, Zap, Brain,
  AlertCircle, Info,
} from 'lucide-react'

interface FilterVal { passed?: boolean; value?: number | string; detail?: string }
interface Leg {
  leg: number; direction: string; strategy: string;
  sl_pct: number; target_pct: number; lots: number;
  filter_log?: Record<string, boolean | FilterVal>
  signal_quality?: string; rr_ratio?: number;
}
interface WatchData {
  ok?: boolean; error?: string;
  regime?: string; vix?: number;
  trading_engine?: string; daily_strategy_filter?: string;
  day_trade_cap?: number; raw_matches?: number;
  executable_legs?: Leg[]
  window?: { start: string; end: string }
  anchor_ym?: number[] | null
  breakout_watch?: Record<string, number | null | undefined>
  scan_order_sample?: string[]
}

function qualityScore(filterLog?: Record<string, boolean | FilterVal>): { passed: number; total: number; grade: string } {
  if (!filterLog) return { passed: 0, total: 0, grade: '?' }
  const entries = Object.values(filterLog)
  const total   = entries.length
  const passed  = entries.filter(v => v === true || (v as FilterVal)?.passed === true).length
  const pct = total > 0 ? passed / total : 0
  const grade = pct >= 0.95 ? 'A+' : pct >= 0.85 ? 'A' : pct >= 0.70 ? 'B' : pct >= 0.55 ? 'C' : 'D'
  return { passed, total, grade }
}

function FilterRow({ name, val }: { name: string; val: boolean | FilterVal }) {
  const ok  = val === true || (val as FilterVal)?.passed === true
  const fail = val === false || (val as FilterVal)?.passed === false
  const v = typeof val === 'object' ? val as FilterVal : null
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-line/10 last:border-0">
      {ok   && <CheckCircle2 size={11} className="shrink-0 mt-0.5 text-green" />}
      {fail && <XCircle      size={11} className="shrink-0 mt-0.5 text-red-l/70" />}
      {!ok && !fail && <div className="w-2.5 h-2.5 shrink-0 mt-0.5 rounded-full bg-text3/30" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={clsx('text-[10px] font-mono font-bold capitalize', ok ? 'text-text2' : fail ? 'text-text3' : 'text-text3')}>
            {name.replace(/_/g, ' ')}
          </span>
          {v?.value != null && (
            <span className="text-[10px] font-mono text-cyan">
              = {typeof v.value === 'number' ? v.value.toFixed(3) : String(v.value)}
            </span>
          )}
        </div>
        {v?.detail && <p className="text-[9px] text-text3 mt-0.5 leading-relaxed">{v.detail}</p>}
      </div>
    </div>
  )
}

function LegCard({ leg, idx }: { leg: Leg; idx: number }) {
  const [open, setOpen] = useState(false)
  const q = qualityScore(leg.filter_log)
  const isCall = leg.direction === 'CALL'
  const rr = leg.rr_ratio ?? (leg.sl_pct > 0 ? leg.target_pct / leg.sl_pct : null)
  const gradeColor = q.grade === 'A+' ? 'text-green border-green/30 bg-green/8'
    : q.grade === 'A'  ? 'text-accent border-accent/30 bg-accent/8'
    : q.grade === 'B'  ? 'text-cyan border-cyan/30 bg-cyan/8'
    : 'text-text3 border-line/30 bg-surface'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.05 }}
      className="rounded-xl border border-line/25 bg-surface/40 overflow-hidden"
    >
      <div className="p-3 flex flex-wrap gap-3 items-center justify-between">
        {/* Direction icon + name */}
        <div className="flex items-center gap-2.5">
          <div className={clsx(
            'w-9 h-9 rounded-xl flex items-center justify-center font-black text-xs shrink-0',
            isCall ? 'bg-green/12 text-green' : 'bg-red/12 text-red-l'
          )}>
            {isCall ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
          </div>
          <div>
            <div className="text-xs font-bold text-text1">
              Leg {leg.leg} · {isCall ? 'CE' : 'PE'} · {leg.direction}
            </div>
            <div className="text-[10px] text-text3 font-mono">
              {leg.strategy.replace(/_/g, ' ')}
            </div>
          </div>
        </div>

        {/* Metrics row */}
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="px-2 py-1 rounded-lg bg-red/8 border border-red/15 text-[10px]">
            <span className="text-text3">SL </span>
            <span className="font-mono font-bold text-red-l">{(leg.sl_pct * 100).toFixed(1)}%</span>
          </div>
          <div className="px-2 py-1 rounded-lg bg-green/8 border border-green/15 text-[10px]">
            <span className="text-text3">Tgt </span>
            <span className="font-mono font-bold text-green">{(leg.target_pct * 100).toFixed(1)}%</span>
          </div>
          {rr && (
            <div className="px-2 py-1 rounded-lg bg-cyan/8 border border-cyan/15 text-[10px]">
              <span className="text-text3">R:R </span>
              <span className="font-mono font-bold text-cyan">{rr.toFixed(1)}x</span>
            </div>
          )}
          <div className="px-2 py-1 rounded-lg bg-accent/8 border border-accent/18 text-[10px]">
            <span className="text-text3">Lots </span>
            <span className="font-mono font-bold text-accent">{leg.lots}</span>
          </div>
          {q.total > 0 && (
            <button
              onClick={() => setOpen(o => !o)}
              className={clsx(
                'flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-bold transition-all',
                gradeColor,
                'hover:border-accent/40'
              )}
            >
              <Brain size={10} />
              {q.grade} · {q.passed}/{q.total}
              {open ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
            </button>
          )}
        </div>
      </div>

      {/* Filter breakdown */}
      <AnimatePresence>
        {open && leg.filter_log && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line/15"
          >
            <div className="p-3 bg-bg/50">
              <div className="label mb-2 flex items-center gap-1">
                <Brain size={10} /> Filter Reasoning
              </div>
              <div className="space-y-0">
                {Object.entries(leg.filter_log).map(([k, v]) => (
                  <FilterRow key={k} name={k} val={v} />
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export function TradePlan() {
  const [data, setData] = useState<WatchData | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const r = await axios.get<WatchData>('/api/daily-watch')
      setData(r.data.ok !== false ? r.data : null)
    } catch { setData(null) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  const legs = data?.executable_legs ?? []

  return (
    <div className="glass-card rounded-2xl p-5 flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <Target size={13} className="text-accent" />
          </div>
          <span className="label">Today's Trade Plan</span>
        </div>
        <div className="flex items-center gap-2">
          {data?.regime && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-cyan/10 text-cyan border border-cyan/20 font-bold">
              {data.regime}
            </span>
          )}
          {data?.trading_engine && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-accent/10 text-accent border border-accent/20 font-bold">
              {data.trading_engine.replace(/_/g, ' ')}
            </span>
          )}
        </div>
      </div>

      {/* Summary row */}
      {data && (
        <div className="grid grid-cols-3 gap-2 mb-4">
          <div className="p-2 rounded-lg bg-surface border border-line/25 text-center">
            <div className="label mb-0.5">VIX</div>
            <div className={clsx(
              'font-mono font-bold text-sm',
              (data.vix ?? 0) < 15 ? 'text-green' : (data.vix ?? 0) > 20 ? 'text-red-l' : 'text-amber'
            )}>{data.vix?.toFixed(1) ?? '—'}</div>
          </div>
          <div className="p-2 rounded-lg bg-surface border border-line/25 text-center">
            <div className="label mb-0.5">Matches</div>
            <div className="font-mono font-bold text-sm text-text1">{data.raw_matches ?? '—'}</div>
          </div>
          <div className="p-2 rounded-lg bg-surface border border-line/25 text-center">
            <div className="label mb-0.5">Cap</div>
            <div className="font-mono font-bold text-sm text-text1">{data.day_trade_cap ?? '—'}</div>
          </div>
        </div>
      )}

      {/* Legs */}
      {loading && (
        <div className="flex-1 flex items-center justify-center text-text3 text-sm">
          <Zap size={14} className="animate-pulse mr-2" /> Loading plan...
        </div>
      )}

      {!loading && legs.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center py-6">
          <AlertCircle size={24} className="text-text3" />
          <p className="text-sm text-text3">
            {data?.error ? data.error : 'No executable legs planned today.'}
          </p>
          <p className="text-[10px] text-text3/60">Bot is scanning — plan generates after daily regime lock.</p>
        </div>
      )}

      {legs.length > 0 && (
        <div className="space-y-2 overflow-y-auto flex-1">
          {legs.map((leg, i) => <LegCard key={leg.leg} leg={leg} idx={i} />)}
        </div>
      )}

      {/* Scan order hint */}
      {data?.scan_order_sample && data.scan_order_sample.length > 0 && (
        <div className="mt-3 pt-3 border-t border-line/20">
          <div className="label mb-1">Scan Order</div>
          <div className="flex flex-wrap gap-1">
            {data.scan_order_sample.map((s, i) => (
              <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-surface text-text3 border border-line/25 font-mono">
                {i + 1}. {s.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}