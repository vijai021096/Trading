/**
 * WatchPage — Today's Setup.
 * Full daily adaptive scan: regime, engine, Nifty context, legs with filter
 * logs, entry window, key levels, scan order, anchor YM.
 */
import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Radar, TrendingUp, TrendingDown, Clock, CheckCircle2, XCircle,
  Brain, ChevronDown, ChevronRight, AlertCircle, RefreshCw,
  Loader2, Layers, Zap, BarChart3, Target, Activity,
  ArrowRight, Sparkles, Info,
} from 'lucide-react'

/* ── Types ──────────────────────────────────────────────────────── */
interface FilterVal { passed?: boolean; value?: number | string; detail?: string }
interface Leg {
  leg: number; direction: string; strategy: string;
  sl_pct: number; target_pct: number; lots: number;
  filter_log?: Record<string, boolean | FilterVal>
}
interface WatchData {
  ok?: boolean; error?: string
  regime?: string; vix?: number
  signal_bar_date?: string; trade_session_date?: string
  day_trade_cap?: number; raw_matches?: number
  executable_legs?: Leg[]
  breakout_watch?: Record<string, number | null | undefined>
  scan_order_sample?: string[]
  trading_engine?: string; daily_strategy_filter?: string
  anchor_ym?: number[] | null
  window?: { start: string; end: string }
}

/* ── Subcomponents ──────────────────────────────────────────────── */
function Chip({ label, value, color = 'surface' }: { label: string; value?: string | number | null; color?: string }) {
  if (value == null) return null
  const cls: Record<string, string> = {
    cyan:    'bg-cyan/10 text-cyan border-cyan/20',
    green:   'bg-green/10 text-green border-green/20',
    red:     'bg-red/10 text-red-l borded/20',
    amber:   'bg-amber/10 text-amber border-amber/20',
    accent:  'bg-accent/10 text-accent border-accent/20',
    surface: 'bg-surface text-text2 border-line/30',
  }
  return (
    <div className={clsx('flex flex-col items-center px-3 py-2 rounded-xl border', cls[color] ?? cls.surface)}>
      <span className="text-[9px] font-bold uppercase tracking-wider opacity-60 mb-0.5">{label}</span>
      <span className="font-mono font-black text-sm">{typeof value === 'number' ? value.toFixed(value > 100 ? 0 : 2) : value}</span>
    </div>
  )
}

function FilterRow({ name, val }: { name: string; val: boolean | FilterVal }) {
  const ok   = val === true || (val as FilterVal)?.passed === true
  const fail = val === false || (val as FilterVal)?.passed === false
  const v    = typeof val === 'object' ? val as FilterVal : null
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-line/8 last:border-0">
      {ok   && <CheckCircle2 size={11} className="shrink-0 mt-0.5 text-green" />}
      {fail && <XCircle      size={11} className="shrink-0 mt-0.5 text-red-l" />}
      {!ok && !fail && <div className="w-2.5 h-2.5 shrink-0 mt-0.5 rounded-full bg-line" />}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={clsx('text-[10px] font-mono font-bold capitalize',
            ok ? 'text-text1' : fail ? 'text-text3' : 'text-text2')}>
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
  const filters = leg.filter_log ? Object.entries(leg.filter_log) : []
  const passed  = filters.filter(([, v]) => v === true || (v as FilterVal)?.passed === true).length
  const failed  = filters.filter(([, v]) => v === false || (v as FilterVal)?.passed === false).length
  const total   = filters.length
  const pct     = total > 0 ? passed / total : 0
  const grade   = pct >= 0.95 ? 'A+' : pct >= 0.85 ? 'A' : pct >= 0.7 ? 'B' : 'C'
  const isCall  = leg.direction === 'CALL'
  const rr      = leg.sl_pct > 0 ? (leg.target_pct / leg.sl_pct) : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.06 }}
      className={clsx(
        'glass-card rounded-2xl overflow-hidden border-l-[3px]',
        isCall ? 'border-l-green' : 'border-l-red'
      )}
    >
      <div className="p-4">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          {/* Left: icon + title */}
          <div className="flex items-center gap-3">
            <div className={clsx(
              'w-10 h-10 rounded-xl flex items-center justify-center text-sm font-black shrink-0',
              isCall ? 'bg-green/12 text-green' : 'bg-red/12 text-red-l'
            )}>
              {isCall ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-black text-text1">Leg {leg.leg}</span>
                <span className={clsx(
                  'text-[10px] font-bold px-1.5 py-0.5 rounded border',
                  isCall ? 'bg-green/10 text-green border-green/25' : 'bg-red/10 text-red-l border-red/25'
                )}>{leg.direction}</span>
              </div>
              <div className="text-[11px] text-text3 font-mono mt-0.5">
                {leg.strategy.replace(/_/g, ' ')}
              </div>
            </div>
          </div>

          {/* Right: metrics + quality */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="grid grid-cols-3 gap-1.5">
              <div className="px-2 py-1.5 rounded-lg bg-red/8 border border-red/15 text-center">
                <div className="text-[9px] text-text3">STOP</div>
                <div className="font-mono font-bold text-xs text-red-l">{(leg.sl_pct * 100).toFixed(1)}%</div>
              </div>
              <div className="px-2 py-1.5 rounded-lg bg-green/8 border border-green/15 text-center">
                <div className="text-[9px] text-text3">TGT</div>
                <div className="font-mono font-bold text-xs text-green">{(leg.target_pct * 100).toFixed(1)}%</div>
              </div>
              <div className="px-2 py-1.5 rounded-lg bg-accent/8 border border-accent/18 text-center">
                <div className="text-[9px] text-text3">LOTS</div>
                <div className="font-mono font-bold text-xs text-accent">{leg.lots}</div>
              </div>
            </div>
            {rr && (
              <div className="px-2 py-1.5 rounded-lg bg-cyan/8 border border-cyan/15 text-center">
                <div className="text-[9px] text-text3">R:R</div>
                <div className="font-mono font-bold text-xs text-cyan">{rr.toFixed(1)}x</div>
              </div>
            )}
            {total > 0 && (
              <button onClick={() => setOpen(o => !o)}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-[11px] font-bold transition-all',
                  pct >= 0.95 ? 'bg-green/10 text-green border-green/25 hover:border-green/40'
                    : pct >= 0.7 ? 'bg-accent/10 text-accent border-accent/25 hover:border-accent/40'
                    : 'bg-surface text-text2 border-line/30 hover:border-accent/30'
                )}
              >
                <Brain size={11} />
                <span>Grade {grade}</span>
                <span className="text-text3">{passed}✓ {failed > 0 ? `${failed}✗` : ''}</span>
                {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              </button>
            )}
          </div>
        </div>

        {/* Filter quality bar */}
        {total > 0 && (
          <div className="mt-3">
            <div className="h-1 rounded-full bg-surface overflow-hidden">
              <motion.div
                className={clsx('h-full rounded-full',
                  pct >= 0.95 ? 'bg-green' : pct >= 0.7 ? 'bg-accent' : 'bg-red/60')}
                initial={{ width: 0 }} animate={{ width: `${pct * 100}%` }}
                transition={{ delay: idx * 0.06 + 0.3, duration: 0.6 }}
              />
            </div>
            <div className="text-[9px] text-text3 mt-0.5">
              Fires when bot is idle, window open, trade slot {idx + 1} available, risk OK
            </div>
          </div>
        )}
      </div>

      {/* Filter detail expansion */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line/20"
          >
            <div className="p-4 bg-bg/60">
              <div className="label mb-3 flex items-center gap-1.5">
                <Brain size={11} /> Filter Reasoning — {leg.strategy.replace(/_/g, ' ')}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
                <div className="space-y-0">
                  {filters.slice(0, Math.ceil(filters.length / 2)).map(([k, v]) => (
                    <FilterRow key={k} name={k} val={v} />
                  ))}
                </div>
                <div className="space-y-0">
                  {filters.slice(Math.ceil(filters.length / 2)).map(([k, v]) => (
                    <FilterRow key={k} name={k} val={v} />
                  ))}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function BreakoutWatch({ bw, price }: { bw: Record<string, number | null | undefined>; price?: number | null }) {
  const allRows = [
    { label: '5D High',    value: bw.prior_5d_high ?? null, color: 'text-green', hint: 'Above = breakout armed' },
    { label: '5D Low',     value: bw.prior_5d_low  ?? null, color: 'text-red-l', hint: 'Below = bear trigger' },
    { label: 'EMA 8',      value: bw.ema8           ?? null, color: 'text-accent', hint: 'Fast trend' },
    { label: 'EMA 21',     value: bw.ema21          ?? null, color: 'text-cyan', hint: 'Slow trend' },
    { label: 'Prev Close', value: bw.last_close      ?? null, color: 'text-text2', hint: 'Reference' },
  ]
  const rows: { label: string; value: number; color: string; hint: string }[] = allRows.filter(
    (r): r is { label: string; value: number; color: string; hint: string } => r.value !== null
  )

  return (
    <div className="glass-card rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
          <BarChart3 size={13} className="text-accent" />
        </div>
        <span className="label">Key Levels</span>
      </div>
      <div className="space-y-2">
        {rows.map(r => {
          const dist = price && r.value ? ((price - r.value) / r.value * 100) : null
          const above = dist != null && dist > 0
          return (
            <div key={r.label} className="flex items-center gap-3">
              <span className="text-[11px] text-text3 w-20 shrink-0">{r.label}</span>
              <span className={clsx('font-mono font-bold text-[11px]', r.color)}>
                {r.value?.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </span>
              {dist != null && (
                <span className={clsx('text-[10px] font-mono ml-auto', above ? 'text-green/70' : 'text-red-l/70')}>
                  {above ? '+' : ''}{dist.toFixed(2)}%
                </span>
              )}
              <span className="text-[9px] text-text3 hidden lg:block w-28">{r.hint}</span>
            </div>
          )
        })}
      </div>
      {/* EMA alignment hint */}
      {bw.ema8 && bw.ema21 && (
        <div className={clsx(
          'mt-3 pt-3 border-t border-line/20 text-[10px] flex items-center gap-1.5',
          (bw.ema8 > bw.ema21!) ? 'text-green/80' : 'text-red-l/80'
        )}>
          {bw.ema8 > bw.ema21!
            ? <><TrendingUp size={10} /> EMA8 &gt; EMA21 — bull stack, trend longs prioritized</>
            : <><TrendingDown size={10} /> EMA8 &lt; EMA21 — bear stack, puts favored</>}
        </div>
      )}
    </div>
  )
}

/* ── Main export ────────────────────────────────────────────────── */
export function WatchPage() {
  const [data, setData]     = useState<WatchData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]       = useState('')
  const [niftyPx, setNiftyPx] = useState<number | null>(null)

  const load = async () => {
    setErr('')
    try {
      const [wr, nr] = await Promise.all([
        axios.get<WatchData>('/api/daily-watch'),
        axios.get('/api/nifty/quote').catch(() => ({ data: {} })),
      ])
      setData(wr.data)
      if (nr.data?.price) setNiftyPx(nr.data.price)
      if (!wr.data.ok && wr.data.error) setErr(String(wr.data.error))
    } catch (e: any) {
      setErr(e.response?.data?.detail || e.message || 'Failed to load')
    } finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  const legs   = data?.executable_legs ?? []
  const bw     = data?.breakout_watch ?? {}
  const hasBw  = Object.keys(bw).length > 0
  const vixColor = (data?.vix ?? 0) < 15 ? 'green' : (data?.vix ?? 0) > 20 ? 'red' : 'amber'

  return (
    <div className="flex-1 overflow-y-auto">
      {/* ── Gradient hero header ─────────────────────────────── */}
      <div className="relative overflow-hidden bg-gradient-to-br from-cyan/8 via-bg to-accent/5 border-b border-line/20 px-4 lg:px-6 py-5">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 right-0 w-56 h-32 bg-cyan/5 rounded-full blur-3xl translate-x-1/4 -translate-y-1/4" />
        </div>
        <div className="relative flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-cyan/80 to-accent flex items-center justify-center shadow-lg shadow-cyan/20">
              <Radar size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-black text-text1 tracking-tight">Today's Setup</h1>
              <p className="text-[11px] text-text3 flex items-center gap-1.5 mt-0.5">
                <Clock size={10} className="text-cyan" />
                {data?.trade_session_date ?? new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}
              </p>
            </div>
          </div>
          {/* Quick regime + VIX strip */}
          {data && (
            <div className="flex items-center gap-2">
              {data.regime && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan/10 border border-cyan/20 text-[11px] font-bold text-cyan">
                  <Layers size={10} /> {data.regime}
                </div>
              )}
              {data.vix != null && (
                <div className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-[11px] font-bold',
                  (data.vix < 15) ? 'bg-green/10 border-green/20 text-green'
                  : (data.vix > 20) ? 'bg-red/10 border-red/20 text-red'
                  : 'bg-amber/10 border-amber/20 text-amber',
                )}>
                  <Activity size={10} /> VIX {data.vix.toFixed(1)}
                </div>
              )}
              <button onClick={load} disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-line/30 text-[11px] text-text3 hover:text-cyan hover:border-cyan/30 transition-all">
                {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                Refresh
              </button>
            </div>
          )}
          {!data && (
            <button onClick={load} disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-line/30 text-[11px] text-text3 hover:text-cyan hover:border-cyan/30 transition-all">
              {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Refresh
            </button>
          )}
        </div>
      </div>
      <div className="p-3 lg:p-4">
      {/* ── Context chips ───────────────────────────────── */}
      {data && (
        <div className="flex flex-wrap gap-2 mb-5">
          <Chip label="Regime" value={data.regime} color="cyan" />
          <Chip label="Engine" value={data.trading_engine?.replace(/_/g, ' ')} color="accent" />
          <Chip label="VIX" value={data.vix?.toFixed(1)} color={vixColor} />
          <Chip label="Filter" value={data.daily_strategy_filter} color="surface" />
          <Chip label="Matches" value={data.raw_matches} color="surface" />
          <Chip label="Trade Cap" value={data.day_trade_cap} color="surface" />
          {data.window && <Chip label="Window" value={`${data.window.start}–${data.window.end}`} color="surface" />}
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────────── */}
      {err && (
        <div className="mb-4 p-4 rounded-xl bg-red/8 border border-red/20 text-red-l text-sm flex items-start gap-2">
          <AlertCircle size={16} className="shrink-0 mt-0.5" />
          <span>{err}</span>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20 gap-3 text-text3">
          <Loader2 size={20} className="animate-spin text-accent" />
          <span className="text-sm">Loading daily setup...</span>
        </div>
      )}

      {/* ── Main content ────────────────────────────────────────── */}
      {!loading && data && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* Left column: legs */}
          <div className="xl:col-span-2 space-y-3">
            <div className="flex items-center gap-2 mb-2">
              <Target size={14} className="text-accent" />
              <span className="label">Executable Legs</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/20 font-bold">
                {legs.length}
              </span>
            </div>

            {legs.length === 0 ? (
              <div className="glass-card rounded-2xl p-8 text-center">
                <Layers size={32} className="text-text3 mx-auto mb-3" />
                <p className="text-sm text-text3">No executable legs yet.</p>
                <p className="text-[11px] text-text3/60 mt-1">
                  The bot hasn't locked the daily plan yet. Check back after 9:20 AM.
                </p>
              </div>
            ) : (
              legs.map((leg, i) => <LegCard key={leg.leg} leg={leg} idx={i} />)
            )}

            {/* Scan order */}
            {data.scan_order_sample && data.scan_order_sample.length > 0 && (
              <div className="glass-card rounded-2xl p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Zap size={13} className="text-cyan" />
                  <span className="label">Scan Priority Order</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {data.scan_order_sample.map((s, i) => (
                    <div key={i} className="flex items-center gap-1">
                      <span className="text-[10px] px-2 py-1 rounded-lg bg-surface border border-line/25 text-text2 font-mono">
                        {i + 1}. {s.replace(/_/g, ' ')}
                      </span>
                      {i < data.scan_order_sample!.length - 1 && (
                        <ArrowRight size={9} className="text-text3" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right column: levels + context */}
          <div className="space-y-4">
            {hasBw && <BreakoutWatch bw={bw} price={niftyPx} />}

            {/* Anchor YM */}
            {data.anchor_ym && data.anchor_ym.length > 0 && (
              <div className="glass-card rounded-2xl p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Activity size={13} className="text-amber" />
                  <span className="label">Anchor Signal Bars</span>
                </div>
                <div className="flex gap-2">
                  {data.anchor_ym.map((y, i) => (
                    <div key={i} className="px-3 py-2 rounded-lg bg-surface border border-line/25 text-center">
                      <div className="text-[9px] text-text3">Bar {i + 1}</div>
                      <div className="font-mono font-bold text-sm text-amber">{y}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Quick reference card */}
            <div className="glass-card rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Info size={13} className="text-text3" />
                <span className="label">Trade Conditions</span>
              </div>
              <div className="space-y-2 text-[11px]">
                {[
                  { label: 'Entry window', ok: true, text: `${data.window?.start ?? '09:16'}–${data.window?.end ?? '13:00'} IST` },
                  { label: 'Regime locked', ok: !!data.regime, text: data.regime ?? 'Pending' },
                  { label: 'VIX acceptable', ok: (data.vix ?? 0) < 20, text: `${data.vix?.toFixed(1)} (< 20)` },
                  { label: 'Trade slots', ok: (data.day_trade_cap ?? 0) > 0, text: `${data.day_trade_cap ?? '?'} max` },
                  { label: 'Legs available', ok: legs.length > 0, text: `${legs.length} planned` },
                ].map((row) => (
                  <div key={row.label} className="flex items-center gap-2">
                    {row.ok
                      ? <CheckCircle2 size={11} className="text-green shrink-0" />
                      : <AlertCircle  size={11} className="text-amber shrink-0" />}
                    <span className="text-text3 w-28 shrink-0">{row.label}</span>
                    <span className="text-text2 font-mono">{row.text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}