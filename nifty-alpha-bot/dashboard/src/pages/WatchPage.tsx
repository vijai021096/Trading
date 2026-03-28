import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  Radar, TrendingUp, TrendingDown, Clock, Activity, AlertCircle,
  RefreshCw, Loader2, Target, Zap, BarChart3, Layers, ChevronRight,
  ChevronDown, CheckCircle2, XCircle, Brain,
} from 'lucide-react'

interface Leg {
  leg: number
  direction: string
  strategy: string
  sl_pct: number
  target_pct: number
  lots: number
  filter_log?: Record<string, unknown>
}

interface WatchResp {
  ok?: boolean
  error?: string
  regime?: string
  vix?: number
  signal_bar_date?: string
  trade_session_date?: string
  day_trade_cap?: number
  raw_matches?: number
  executable_legs?: Leg[]
  breakout_watch?: Record<string, number | null | undefined>
  scan_order_sample?: string[]
  trading_engine?: string
  daily_strategy_filter?: string
  anchor_ym?: number[] | null
  window?: { start: string; end: string }
}

function triggerHints(bw: Record<string, number | null | undefined> | undefined) {
  if (!bw) return []
  const lc = bw.last_close
  const hi = bw.prior_5d_high
  const lo = bw.prior_5d_low
  const e8 = bw.ema8
  const e21 = bw.ema21
  const hints: string[] = []
  if (lc != null && hi != null) {
    hints.push(
      lc > hi
        ? `Price ${lc.toFixed(0)} is ABOVE 5D high ${hi.toFixed(0)} → breakout momentum / trend long bias can arm.`
        : `Below 5D high ${hi.toFixed(0)} (close ${lc.toFixed(0)}) → needs push through for breakout-style entries.`,
    )
  }
  if (lc != null && lo != null) {
    hints.push(
      lc < lo
        ? `Price ${lc.toFixed(0)} is UNDER 5D low ${lo.toFixed(0)} → bearish / reversal context possible.`
        : `Held above 5D low ${lo.toFixed(0)}.`,
    )
  }
  if (lc != null && e8 != null && e21 != null) {
    hints.push(
      lc > e8 && e8 > e21
        ? `Bull stack: close > EMA8 > EMA21 — trend continuation strategies prioritized in scan order.`
        : lc < e8 && e8 < e21
          ? `Bear stack: close < EMA8 < EMA21 — puts favored where regime allows.`
          : `EMA8/21 cross-current — mixed; mean-reversion / range plays may compete with trend legs.`,
    )
  }
  return hints
}

// ── Filter log row: shows one indicator check ──────────────────────
function FilterRow({ name, val }: { name: string; val: unknown }) {
  if (val == null || typeof val !== 'object') return null
  const v = val as Record<string, unknown>
  const passed = v.passed as boolean | undefined
  const value  = v.value
  const detail = v.detail as string | undefined
  return (
    <div className="flex items-start gap-2 py-1 border-b border-line/10 last:border-0">
      {passed === true  && <CheckCircle2 size={13} className="shrink-0 text-green mt-0.5" />}
      {passed === false && <XCircle      size={13} className="shrink-0 text-red-l mt-0.5" />}
      {passed == null   && <span className="w-3.5 h-3.5 shrink-0 rounded-full bg-text3/20 mt-0.5 inline-block" />}
      <div className="min-w-0 flex-1">
        <span className={clsx('font-mono text-[10px] font-bold', passed ? 'text-text2' : 'text-text3')}>
          {name.replace(/_/g, ' ')}
        </span>
        {value != null && (
          <span className="ml-1.5 text-[10px] font-mono text-cyan-l">
            = {typeof value === 'number' ? (value as number).toFixed(3) : String(value)}
          </span>
        )}
        {detail && <p className="text-[9px] text-text3 mt-0.5 leading-relaxed">{detail}</p>}
      </div>
    </div>
  )
}

// ── Leg card with expandable filter log ────────────────────────────
function LegCard({ leg, i }: { leg: Leg; i: number }) {
  const [open, setOpen] = useState(false)
  const filters = leg.filter_log ? Object.entries(leg.filter_log) : []
  const passed  = filters.filter(([, v]) => (v as any)?.passed === true).length
  const failed  = filters.filter(([, v]) => (v as any)?.passed === false).length

  return (
    <div className="rounded-xl border border-line/20 bg-surface/40 overflow-hidden">
      <div className="p-4 flex flex-wrap gap-4 items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={clsx(
            'w-10 h-10 rounded-xl flex items-center justify-center font-black text-sm',
            leg.direction === 'CALL' ? 'bg-green/15 text-green' : 'bg-red/15 text-red-l',
          )}>
            {leg.direction === 'CALL' ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
          </div>
          <div>
            <div className="text-sm font-bold text-text1">
              Leg {leg.leg} · {leg.strategy.replace(/_/g, ' ')}
            </div>
            <div className="text-[10px] text-text3 font-mono">
              Fires when bot is idle, window open, trades_today = {i}, risk OK
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-[11px] items-center">
          <div className="px-3 py-1.5 rounded-lg bg-red/10 border border-red/15">
            <span className="text-text3">SL </span>
            <span className="font-mono font-bold text-red-l">{(leg.sl_pct * 100).toFixed(1)}%</span>
          </div>
          <div className="px-3 py-1.5 rounded-lg bg-green/10 border border-green/15">
            <span className="text-text3">Tgt </span>
            <span className="font-mono font-bold text-green-l">{(leg.target_pct * 100).toFixed(1)}%</span>
          </div>
          <div className="px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/20">
            <span className="text-text3">Lots </span>
            <span className="font-mono font-bold text-accent">{leg.lots}</span>
          </div>
          {filters.length > 0 && (
            <button
              onClick={() => setOpen(o => !o)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface border border-line/25 text-[10px] font-bold text-text2 hover:border-accent/30 hover:text-accent transition-all"
            >
              <Brain size={11} />
              {passed}✓ {failed > 0 ? `${failed}✗` : ''}
              {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            </button>
          )}
        </div>
      </div>
      <AnimatePresence>
        {open && filters.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden border-t border-line/15"
          >
            <div className="p-4 bg-surface/60">
              <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2 flex items-center gap-1">
                <Brain size={11} /> Bot reasoning — {leg.strategy.replace(/_/g, ' ')}
              </div>
              <div className="space-y-0">
                {filters.map(([k, v]) => <FilterRow key={k} name={k} val={v} />)}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function WatchPage() {
  const [data, setData] = useState<WatchResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = async () => {
    setErr('')
    try {
      const r = await axios.get<WatchResp>('/api/daily-watch')
      setData(r.data)
      if (!r.data.ok && r.data.error) setErr(String(r.data.error))
    } catch (e: any) {
      setErr(e.response?.data?.detail || e.message || 'Failed to load')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 20_000)
    return () => clearInterval(id)
  }, [])

  const hints = useMemo(() => triggerHints(data?.breakout_watch), [data])

  const regimeColor = (r?: string) => {
    if (!r) return 'text-text3'
    if (r.includes('UP') || r.includes('BULL')) return 'text-green-l'
    if (r.includes('DOWN') || r.includes('BEAR')) return 'text-red-l'
    if (r.includes('RANGE') || r.includes('CHOP')) return 'text-amber'
    return 'text-cyan-l'
  }

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-5 pb-24">

      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-accent/30 to-cyan/20 flex items-center justify-center border border-accent/25 shadow-lg shadow-accent/10">
            <Radar size={22} className="text-accent" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight text-text1">Adaptive Watch</h1>
            <p className="text-[11px] text-text3 max-w-xl">
              Same engine as daily backtest: last <span className="text-text2 font-semibold">completed</span> daily bar + live VIX.
              Entries fire in <span className="text-cyan font-mono">{data?.window?.start ?? '—'}–{data?.window?.end ?? '—'} IST</span> when the bot is idle and risk allows.
            </p>
          </div>
        </div>
        <button onClick={() => { setLoading(true); load() }}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold bg-surface border border-line/25 text-text2 hover:border-accent/30 hover:text-accent transition-all">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </motion.div>

      {err && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red/10 border border-red/20 text-red-l text-sm">
          <AlertCircle size={16} /> {err}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Regime + meta */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
          className="lg:col-span-1 glass-card rounded-2xl p-5 neon-border relative overflow-hidden">
          <div className="absolute top-0 right-0 w-32 h-32 bg-accent/5 rounded-full blur-3xl pointer-events-none" />
          <div className="flex items-center gap-2 mb-4">
            <Activity size={16} className="text-accent" />
            <span className="text-xs font-bold text-text1 uppercase tracking-widest">Regime & session</span>
          </div>
          <div className={clsx('text-2xl font-black mb-1', regimeColor(data?.regime))}>
            {data?.regime ?? (loading ? '…' : '—')}
          </div>
          <div className="space-y-2 text-[11px] text-text3 font-medium">
            <div className="flex justify-between border-b border-line/10 py-1.5">
              <span>Signal bar (EOD)</span>
              <span className="font-mono text-text2">{data?.signal_bar_date ?? '—'}</span>
            </div>
            <div className="flex justify-between border-b border-line/10 py-1.5">
              <span>Session date</span>
              <span className="font-mono text-text2">{data?.trade_session_date ?? '—'}</span>
            </div>
            <div className="flex justify-between border-b border-line/10 py-1.5">
              <span>Live VIX</span>
              <span className="font-mono text-cyan">{data?.vix?.toFixed(2) ?? '—'}</span>
            </div>
            <div className="flex justify-between border-b border-line/10 py-1.5">
              <span>Day trade cap</span>
              <span className="font-mono text-text2">{data?.day_trade_cap ?? '—'} <span className="text-text3">(VIX + cfg)</span></span>
            </div>
            <div className="flex justify-between py-1.5">
              <span>Strategy filter</span>
              <span className="font-mono text-amber">{data?.daily_strategy_filter ?? '—'}</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span>Anchor month (sizing)</span>
              <span className="font-mono text-text2">
                {data?.anchor_ym ? `${data.anchor_ym[0]}-${String(data.anchor_ym[1]).padStart(2, '0')}` : 'first-run month'}
              </span>
            </div>
          </div>
        </motion.div>

        {/* Planned legs */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
          className="lg:col-span-2 glass-card rounded-2xl p-5 neon-border">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-green" />
              <span className="text-xs font-bold text-text1 uppercase tracking-widest">Planned legs (today)</span>
            </div>
            <span className="text-[10px] font-bold text-text3 bg-surface px-2 py-1 rounded-lg border border-line/20">
              raw matches: {data?.raw_matches ?? 0}
            </span>
          </div>
          <p className="text-[11px] text-text3 mb-4">Legs generated by the <span className="text-cyan font-semibold">daily-adaptive engine</span> from yesterday's EOD bar. Each leg is a full setup with direction, strategy, SL, target and size — the bot fires them in this order when the entry window opens.</p>
          {!data?.executable_legs?.length ? (
            <div className="text-sm text-text3 py-8 text-center border border-dashed border-line/25 rounded-xl">
              No executable legs on this bar — regime filter or strategy rules did not produce a trade list.
              Check <span className="text-accent">Logs</span> for <code className="text-cyan">DAILY_ADAPTIVE_SCAN</code>.
            </div>
          ) : (
            <div className="space-y-3">
              {data.executable_legs.map((leg, i) => (
                <LegCard key={i} leg={leg} i={i} />
              ))}
              <p className="text-[10px] text-text3 text-center pt-1">
                Click <Brain size={10} className="inline" /> on any leg to see every filter the bot checked
              </p>
            </div>
          )}
        </motion.div>
      </div>

      {/* Breakout watch + scan order */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          className="glass-card rounded-2xl p-5 neon-border">
          <div className="flex items-center gap-2 mb-4">
            <Target size={16} className="text-amber" />
            <span className="text-xs font-bold text-text1 uppercase tracking-widest">Breakout watch</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4">
            {[
              ['5D High', data?.breakout_watch?.prior_5d_high],
              ['5D Low', data?.breakout_watch?.prior_5d_low],
              ['Last close', data?.breakout_watch?.last_close],
              ['EMA8', data?.breakout_watch?.ema8],
              ['EMA21', data?.breakout_watch?.ema21],
              ['RSI14', data?.breakout_watch?.rsi14],
              ['VWAP(5)', data?.breakout_watch?.vwap5],
            ].map(([k, v]) => (
              <div key={String(k)} className="rounded-lg bg-surface/50 border border-line/15 p-2.5">
                <div className="text-[9px] font-bold text-text3 uppercase">{k}</div>
                <div className="text-sm font-mono font-bold text-text1">
                  {v == null ? '—' : typeof v === 'number' ? v.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : String(v)}
                </div>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            <div className="text-[10px] font-bold text-text3 uppercase tracking-wider flex items-center gap-1">
              <Zap size={12} /> What would strengthen triggers
            </div>
            {hints.length === 0 ? (
              <p className="text-xs text-text3">Load data to see narrative hints.</p>
            ) : (
              hints.map((h, i) => (
                <div key={i} className="flex gap-2 text-xs text-text2 leading-relaxed border-l-2 border-accent/40 pl-3 py-1">
                  <ChevronRight size={14} className="shrink-0 text-accent mt-0.5" />
                  {h}
                </div>
              ))
            )}
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}
          className="glass-card rounded-2xl p-5 neon-border">
          <div className="flex items-center gap-2 mb-4">
            <BarChart3 size={16} className="text-cyan" />
            <span className="text-xs font-bold text-text1 uppercase tracking-widest">Strategy scan order</span>
          </div>
          <p className="text-[11px] text-text3 mb-3">
            Daily-adaptive engine evaluates these strategies in priority order for this regime. Only legs that pass all filters become executable. All strategies use daily EOD bars — not intraday.
          </p>
          <ol className="space-y-2">
            {(data?.scan_order_sample ?? []).map((s, i) => {
              const desc: Record<string, string> = {
                TREND_CONTINUATION: 'EMA pullback in established trend',
                BREAKOUT_MOMENTUM:  'N-candle range breakout + volume',
                EMA_FRESH_CROSS:    'Fresh EMA8/21 crossover',
                REVERSAL_SNAP:      'RSI exhaustion + reversal candle',
                GAP_FADE:           'Fade large opening gaps',
                RANGE_BOUNCE:       'S/R bounce in ranging market',
                INSIDE_BAR_BREAK:   'Inside bar compression breakout',
                VWAP_CROSS:         'VWAP reclaim signal',
              }
              return (
                <li key={s + i} className="flex items-center gap-3">
                  <span className="w-7 h-7 rounded-lg bg-cyan/10 border border-cyan/20 font-mono font-bold text-cyan flex items-center justify-center text-xs shrink-0">
                    {i + 1}
                  </span>
                  <div>
                    <div className="text-sm font-semibold text-text1">{s.replace(/_/g, ' ')}</div>
                    {desc[s] && <div className="text-[10px] text-text3">{desc[s]}</div>}
                  </div>
                </li>
              )
            })}
            {!(data?.scan_order_sample?.length) && (
              <li className="text-text3 text-sm">—</li>
            )}
          </ol>
          <div className="mt-4 flex items-start gap-2 p-3 rounded-xl bg-surface/60 border border-line/15">
            <Clock size={14} className="text-text3 shrink-0 mt-0.5" />
            <p className="text-[11px] text-text3 leading-relaxed">
              Bot logs <code className="text-accent">DAILY_ADAPTIVE_SCAN</code> once when the entry window starts, then{' '}
              <code className="text-green">ENTRY</code> per leg with <code className="text-text2">engine: daily_adaptive</code>.
              Tune filter via <code className="text-amber">DAILY_STRATEGY_FILTER</code> in <code>.env</code>.
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
