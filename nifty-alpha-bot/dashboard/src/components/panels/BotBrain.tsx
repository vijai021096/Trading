/**
 * BotBrain — complete bot intelligence surface:
 *   • State narrative + thinking bullets
 *   • Entry window countdown bar
 *   • "Waiting For" checklist
 *   • P(success) probability estimate
 *   • Last trade context
 *   • Scan / skip stats
 */
import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import {
  Brain, Clock, Target, Zap, CheckCircle2, AlertCircle,
  TrendingUp, TrendingDown, Activity, Hourglass, BarChart2,
  ThumbsUp, ThumbsDown, Info, XOctagon,
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

/* ── Entry window progress bar ─────────────────────────────────── */
function WindowClock({ thinking }: { thinking?: string }) {
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  // Market session: 9:15 – 15:30. Entry window: typically 9:16 – 13:00
  const MARKET_OPEN  = 9  * 60 + 15
  const MARKET_CLOSE = 15 * 60 + 30
  const ENTRY_CLOSE  = 13 * 60 + 0

  const marketOpen = nowMin >= MARKET_OPEN && nowMin <= MARKET_CLOSE
  const inEntry    = nowMin >= MARKET_OPEN && nowMin <= ENTRY_CLOSE
  const pct = marketOpen
    ? Math.min(100, ((nowMin - MARKET_OPEN) / (MARKET_CLOSE - MARKET_OPEN)) * 100)
    : nowMin < MARKET_OPEN ? 0 : 100

  const label = nowMin < MARKET_OPEN
    ? `Opens in ${MARKET_OPEN - nowMin}m`
    : nowMin > MARKET_CLOSE
    ? 'Market closed'
    : inEntry ? `Entry window · ${ENTRY_CLOSE - nowMin}m left` : 'Entry window closed'

  const barColor = !marketOpen ? 'bg-text3/30' : inEntry ? 'bg-accent' : 'bg-amber/60'
  const badge = !marketOpen
    ? { text: nowMin < MARKET_OPEN ? 'PRE' : 'CLOSED', cls: 'text-text3 bg-surface border-line/30' }
    : inEntry
    ? { text: 'OPEN', cls: 'text-accent bg-accent/10 border-accent/25 animate-pulse' }
    : { text: 'POST', cls: 'text-amber bg-amber/10 border-amber/25' }

  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <Clock size={10} className={inEntry ? 'text-accent' : 'text-text3'} />
          <span className="text-[10px] text-text3 font-medium">Market Session</span>
          <span className={clsx('text-[9px] font-black px-1.5 py-0.5 rounded border', badge.cls)}>
            {badge.text}
          </span>
        </div>
        <span className="font-mono text-[10px] text-text2">
          {now.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', hour12:false, timeZone:'Asia/Kolkata' })} IST
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-surface overflow-hidden">
        <motion.div className={clsx('h-full rounded-full transition-all', barColor)}
          initial={{ width:0 }} animate={{ width:`${pct}%` }} transition={{ duration:0.8 }} />
      </div>
      <p className={clsx('text-[10px] mt-0.5', inEntry ? 'text-accent/80' : 'text-text3')}>{label}</p>
    </div>
  )
}

/* ── Probability of success gauge ────────────────────────────────*/
function ProbabilityGauge({ botStatus }: { botStatus: any }) {
  const conviction = botStatus?.trend_conviction ?? 0
  const regime    = (botStatus?.regime ?? botStatus?.daily_regime ?? '').toUpperCase()
  const vix       = botStatus?.regime_vix ?? null
  const adx       = botStatus?.regime_adx ?? null
  const state     = botStatus?.state ?? 'IDLE'
  const trades    = botStatus?.trades_today ?? 0
  const maxTrades = botStatus?.max_trades ?? 3
  const consLoss  = botStatus?.consecutive_losses ?? 0
  const paused    = botStatus?.paused ?? false
  const halted    = botStatus?.halt_active ?? false

  // Score components (0-100)
  const scoreConviction = Math.min(conviction, 100)
  const scoreRegime = regime.includes('STRONG_TREND') ? 85
    : regime.includes('TREND') ? 70
    : regime.includes('SIDEWAYS') ? 40
    : regime.includes('HIGH_VOL') ? 30
    : 55
  const scoreVix = vix == null ? 60 : vix < 14 ? 85 : vix < 18 ? 75 : vix < 22 ? 60 : vix < 26 ? 40 : 20
  const scoreAdx = adx == null ? 60 : adx > 30 ? 85 : adx > 20 ? 70 : 40
  const scoreCap  = maxTrades > 0 ? Math.min(100, ((maxTrades - trades) / maxTrades) * 100) : 0
  const penaltyConsLoss = consLoss >= 3 ? -30 : consLoss >= 2 ? -15 : 0

  let base = (scoreConviction * 0.30 + scoreRegime * 0.25 + scoreVix * 0.20 + scoreAdx * 0.15 + scoreCap * 0.10)
  base += penaltyConsLoss
  if (paused || halted) base *= 0.1
  const prob = Math.max(0, Math.min(100, Math.round(base)))

  const color = prob >= 65 ? 'text-green bg-green' : prob >= 45 ? 'text-amber bg-amber' : 'text-red bg-red'
  const textColor = prob >= 65 ? 'text-green' : prob >= 45 ? 'text-amber' : 'text-red'
  const label = halted ? 'HALTED' : paused ? 'PAUSED' : prob >= 65 ? 'High' : prob >= 45 ? 'Medium' : 'Low'

  return (
    <div className="mb-3 p-2.5 rounded-xl bg-surface/50 border border-line/25">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <BarChart2 size={10} className={textColor} />
          <span className="text-[10px] font-bold text-text3">Setup Quality Score</span>
        </div>
        <span className={clsx('text-[11px] font-black font-mono', textColor)}>
          {halted || paused ? label : `${prob}% · ${label}`}
        </span>
      </div>
      <div className="h-2 rounded-full bg-bg overflow-hidden">
        <motion.div
          className={clsx('h-full rounded-full', color.split(' ')[1])}
          initial={{ width:0 }} animate={{ width: `${halted||paused ? 5 : prob}%` }}
          transition={{ duration:1, ease:'easeOut' }}
        />
      </div>
      <div className="flex gap-2 mt-1.5">
        {[['Conviction', scoreConviction, 'text-accent'], ['Regime', scoreRegime, 'text-cyan'],
          ['VIX', scoreVix, 'text-amber'], ['ADX', scoreAdx, 'text-green']].map(([lbl, val, cls]) => (
          <div key={lbl as string} className="flex-1 text-center">
            <div className={clsx('text-[9px] font-mono font-bold', cls)}>{Math.round(val as number)}</div>
            <div className="text-[8px] text-text3">{lbl}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Conditions checklist ────────────────────────────────────────*/
function ConditionsCheck({ botStatus }: { botStatus: any }) {
  const thinking   = (botStatus?.thinking ?? '').toLowerCase()
  const state      = botStatus?.state ?? 'IDLE'
  const trades     = botStatus?.trades_today ?? 0
  const maxTrades  = botStatus?.max_trades ?? 3
  const vix        = botStatus?.regime_vix ?? null
  const vixMax     = (botStatus as any)?.vix_max ?? 18
  const kiteOk     = botStatus?.kite_connected ?? false
  const paused     = botStatus?.paused ?? false
  const halted     = botStatus?.halt_active ?? false
  const drawdown   = botStatus?.drawdown_pct ?? 0
  const maxDraw    = botStatus?.max_drawdown_pct ?? 15
  const consLoss   = botStatus?.consecutive_losses ?? 0
  const hasPlan    = !!(botStatus?.last_scan?.candidates?.length)
  const nowMin     = new Date().getHours() * 60 + new Date().getMinutes()
  const inWindow   = nowMin >= 9*60+15 && nowMin <= 13*60

  const checks: { label: string; ok: boolean; warn?: boolean; detail?: string }[] = [
    { label: 'Kite connected',       ok: kiteOk,                       detail: kiteOk ? 'Live data flowing' : 'Reconnect in Settings' },
    { label: 'Not halted/paused',    ok: !halted && !paused,           warn: paused && !halted, detail: halted ? 'EMERGENCY HALT' : paused ? 'Trading paused' : 'Active' },
    { label: 'Entry window open',    ok: inWindow,                     detail: inWindow ? '9:16 – 13:00 IST' : 'Outside entry hours' },
    { label: 'Trade cap available',  ok: trades < maxTrades,           detail: `${trades}/${maxTrades} used` },
    { label: 'VIX acceptable',       ok: vix == null || vix <= vixMax, detail: vix != null ? `${vix?.toFixed(1)} vs max ${vixMax}` : 'No VIX data' },
    { label: 'Drawdown safe',        ok: drawdown < maxDraw * 0.8,     detail: `${drawdown.toFixed(1)}% of ${maxDraw}% max` },
    { label: 'No cons. loss block',  ok: consLoss < 3,                 detail: consLoss > 0 ? `${consLoss} consecutive losses` : 'Clean slate' },
    { label: 'Scan has candidates',  ok: hasPlan,                      detail: hasPlan ? `${botStatus?.last_scan?.signals_detected ?? 0} signals` : 'No signal yet' },
  ]

  const metCount  = checks.filter(c => c.ok).length
  const allMet    = metCount === checks.length
  const blockers  = checks.filter(c => !c.ok)

  return (
    <div className="mb-3 rounded-xl bg-surface/50 border border-line/25 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-line/15">
        <div className="flex items-center gap-1.5">
          <Hourglass size={10} className={allMet ? 'text-green' : 'text-amber'} />
          <span className="text-[10px] font-bold text-text3">
            {allMet ? 'All conditions met' : `${metCount}/${checks.length} conditions met`}
          </span>
        </div>
        {!allMet && (
          <span className="text-[9px] font-bold text-amber">{blockers.length} blocking</span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-0">
        {checks.map((c, i) => (
          <div key={i} className={clsx(
            'flex items-start gap-2 px-3 py-1.5 border-b border-line/10 last:border-0 text-[10px]',
            !c.ok && !c.warn ? 'bg-red/3' : c.warn ? 'bg-amber/3' : ''
          )}>
            {c.ok
              ? <CheckCircle2 size={10} className="text-green shrink-0 mt-0.5" />
              : c.warn
              ? <AlertCircle  size={10} className="text-amber shrink-0 mt-0.5" />
              : <XOctagon     size={10} className="text-red   shrink-0 mt-0.5" />}
            <span className={c.ok ? 'text-text2' : c.warn ? 'text-amber' : 'text-red/80'}>{c.label}</span>
            {c.detail && (
              <span className="ml-auto text-[9px] text-text3 font-mono shrink-0">{c.detail}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Last trade context ──────────────────────────────────────────*/
function LastTrade({ botStatus }: { botStatus: any }) {
  const pnl    = botStatus?.last_trade_pnl
  const reason = botStatus?.last_exit_reason
  const lastTs = (botStatus as any)?.last_trade_ts ?? null
  if (pnl == null && !reason) return null
  const win = (pnl ?? 0) > 0

  const ago = (() => {
    if (!lastTs) return null
    const diffMin = Math.round((Date.now() - new Date(lastTs).getTime()) / 60_000)
    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    return `${Math.round(diffMin / 60)}h ago`
  })()

  return (
    <div className={clsx('mb-3 p-2.5 rounded-xl border text-[10px]',
      win ? 'bg-green/5 border-green/20' : 'bg-red/5 border-red/20')}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider font-bold text-text3">
          {win ? <ThumbsUp size={9} className="text-green" /> : <ThumbsDown size={9} className="text-red" />}
          Last Trade
        </div>
        {ago && <span className="text-[9px] text-text3 font-mono">{ago}</span>}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-text2">{reason ?? (win ? 'Target hit' : 'Stop loss')}</span>
        {pnl != null && (
          <span className={clsx('font-mono font-bold', win ? 'text-green' : 'text-red-l')}>
            {win?'+':''}₹{Math.abs(pnl).toFixed(0)}
          </span>
        )}
      </div>
    </div>
  )
}

/* ── Main export ─────────────────────────────────────────────────*/
export function BotBrain() {
  const { botStatus } = useTradingStore()

  const thinking  = botStatus?.thinking ?? ''
  const state     = botStatus?.state    ?? 'IDLE'
  const trades    = botStatus?.trades_today ?? 0
  const maxTrades = botStatus?.max_trades   ?? 3
  const engine    = botStatus?.trading_engine ?? (botStatus?.strategies as any)?.active_engine ?? null
  const regime    = botStatus?.daily_regime   ?? botStatus?.regime ?? null
  const filter    = botStatus?.daily_strategy_filter ?? null
  const scanCount = (botStatus as any)?.scan_count_today ?? null
  const skipped   = (botStatus as any)?.skipped_today   ?? null
  const narrative = botStatus?.narrative ?? null

  // Parse thinking into readable bullets
  const bullets = useMemo(() => {
    const source = narrative || thinking
    if (!source) return []
    // Split on em-dash, pipe, bullet chars, or sentence endings
    return source
      .split(/\s*[—·|•]\s*|(?<=\.)\s+(?=[A-Z])/)
      .map(s => s.trim())
      .filter(s => s.length > 3)
      .slice(0, 5)
  }, [thinking, narrative])

  // What the bot is deciding right now
  const decision = useMemo(() => {
    if (!thinking) return null
    const t = thinking.toLowerCase()
    if (t.includes('taking entry') || t.includes('entering')) return { text: 'Taking entry', color: 'text-green', icon: TrendingUp }
    if (t.includes('closing') || t.includes('exit'))          return { text: 'Closing position', color: 'text-amber', icon: TrendingDown }
    if (t.includes('waiting for signal'))                      return { text: 'Scanning for signal', color: 'text-accent', icon: Zap }
    if (t.includes('halted') || t.includes('emergency'))      return { text: 'HALTED', color: 'text-red', icon: XOctagon }
    if (t.includes('paused'))                                  return { text: 'Paused', color: 'text-amber', icon: AlertCircle }
    if (t.includes('market closed') || t.includes('pre-market')) return { text: 'Market closed', color: 'text-text3', icon: Clock }
    return { text: thinking.slice(0, 60) + (thinking.length > 60 ? '…' : ''), color: 'text-text2', icon: Info }
  }, [thinking])

  return (
    <div className="glass-card rounded-2xl p-4 h-full flex flex-col overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <Brain size={13} className="text-accent" />
          </div>
          <span className="text-[11px] font-bold text-text2 uppercase tracking-wider">Bot Intelligence</span>
        </div>
        <div className="flex items-center gap-1.5">
          {state === 'ACTIVE' && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-60" />
              <span className="relative rounded-full h-2 w-2 bg-green" />
            </span>
          )}
          <span className={clsx('text-[9px] font-black px-2 py-0.5 rounded border',
            state === 'ACTIVE'   ? 'bg-green/10 text-green border-green/25'
            : botStatus?.halt_active ? 'bg-red/10 text-red border-red/25 animate-pulse'
            : botStatus?.paused  ? 'bg-amber/10 text-amber border-amber/25'
            : 'bg-surface text-text3 border-line/30')}>
            {botStatus?.halt_active ? 'HALTED' : botStatus?.paused ? 'PAUSED' : state}
          </span>
          <span className="text-[9px] font-mono text-text3">{trades}/{maxTrades}</span>
        </div>
      </div>

      {/* Regime + engine chips */}
      {(regime || engine || filter) && (
        <div className="flex flex-wrap gap-1 mb-3">
          {regime && (
            <span className={clsx(
              'text-[9px] px-2 py-0.5 rounded-md border font-bold',
              regime.includes('STRONG') ? 'bg-green/12 text-green border-green/25'
              : regime.includes('UP') || regime.includes('BULL') ? 'bg-green/8 text-green/80 border-green/20'
              : regime.includes('DOWN') || regime.includes('BEAR') ? 'bg-red/8 text-red border-red/20'
              : 'bg-cyan/8 text-cyan border-cyan/20'
            )}>
              🌐 {regime}
            </span>
          )}
          {engine && (
            <span className="text-[9px] px-2 py-0.5 rounded-md bg-accent/10 text-accent border border-accent/20 font-bold">
              ⚙ {engine.replace(/_/g,' ')}
            </span>
          )}
          {filter && filter !== 'BOTH' && (
            <span className="text-[9px] px-2 py-0.5 rounded-md bg-surface text-text3 border border-line/30 font-bold">
              filter: {filter}
            </span>
          )}
          {scanCount != null && <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface text-text3 border border-line/25">{scanCount} scans</span>}
          {skipped != null && skipped > 0 && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber/8 text-amber border border-amber/20">{skipped} skipped</span>}
        </div>
      )}

      {/* Current decision banner */}
      {decision && (
        <div className={clsx(
          'flex items-center gap-2 mb-3 px-3 py-2 rounded-xl bg-surface/60 border border-line/25 text-[11px] font-medium',
          decision.color
        )}>
          <decision.icon size={12} className="shrink-0" />
          {decision.text}
        </div>
      )}

      {/* Narrative bullets */}
      {bullets.length > 0 && (
        <div className="mb-3 space-y-1">
          <AnimatePresence mode="popLayout">
            {bullets.map((line, i) => (
              <motion.div key={line.slice(0,20)}
                initial={{ opacity:0, x:-6 }} animate={{ opacity:1, x:0 }}
                transition={{ delay: i * 0.03 }}
                className="flex items-start gap-2 text-[10px] leading-relaxed">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-accent/60 shrink-0" />
                <span className={i === 0 ? 'text-text1 font-medium' : 'text-text2'}>{line}</span>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      {!thinking && (
        <p className="text-[10px] text-text3 italic mb-3 animate-pulse">Waiting for heartbeat from bot...</p>
      )}

      {/* Market session bar */}
      <WindowClock thinking={thinking} />

      {/* Probability gauge */}
      <ProbabilityGauge botStatus={botStatus} />

      {/* Conditions checklist */}
      <ConditionsCheck botStatus={botStatus} />

      {/* Last trade */}
      <LastTrade botStatus={botStatus} />

      {/* Bottom stats */}
      <div className="mt-auto pt-2 border-t border-line/20 flex items-center gap-3 text-[9px] text-text3">
        <Activity size={9} className="text-accent shrink-0" />
        <span>{trades}/{maxTrades} trades today</span>
        {(botStatus as any)?.lots_planning != null && (
          <><Target size={9} className="text-cyan shrink-0" />
          <span className="text-cyan">{(botStatus as any).lots_planning} lots planned</span></>
        )}
        {botStatus?.consecutive_losses != null && botStatus.consecutive_losses > 0 && (
          <span className="text-red ml-auto">{botStatus.consecutive_losses}x losses</span>
        )}
      </div>
    </div>
  )
}