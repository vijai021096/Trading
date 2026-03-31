/**
 * MarketIntel — regime, trend, signal quality, and scan summary.
 * Strengthened bull regime display. Shows full market narrative.
 */
import { useMemo } from 'react'
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { Brain, Radar, Wind, ArrowUp, ArrowDown, Minus, Flame, TrendingUp, Shield } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

/* ── Regime classification ────────────────────────────────────── */
function classifyRegime(regime: string | null | undefined): {
  cls: string; glow: string; label: string; bullish: boolean
} {
  const r = (regime ?? '').toUpperCase()
  if (r.includes('STRONG_TREND_UP') || r.includes('STRONG_BULL'))
    return { cls:'text-green bg-green/12 border-green/30', glow:'shadow-green/20', label: regime!, bullish: true }
  if (r.includes('TREND_UP') || r.includes('BULL'))
    return { cls:'text-green bg-green/8  border-green/20', glow:'shadow-green/10', label: regime!, bullish: true }
  if (r.includes('STRONG_TREND_DOWN') || r.includes('STRONG_BEAR'))
    return { cls:'text-red   bg-red/12   border-red/30',   glow:'shadow-red/20',   label: regime!, bullish: false }
  if (r.includes('TREND_DOWN') || r.includes('BEAR'))
    return { cls:'text-red   bg-red/8    border-red/20',   glow:'shadow-red/10',   label: regime!, bullish: false }
  if (r.includes('HIGH_VOL') || r.includes('VOLATILE'))
    return { cls:'text-amber bg-amber/10 border-amber/25', glow:'shadow-amber/15', label: regime!, bullish: false }
  if (r.includes('SIDEWAYS') || r.includes('RANGE'))
    return { cls:'text-text2 bg-surface  border-line/30',  glow:'',               label: regime!, bullish: false }
  return   { cls:'text-text3 bg-surface  border-line/20',  glow:'',               label: regime ?? 'Unknown', bullish: false }
}

/* ── Score bar ────────────────────────────────────────────────── */
function ScoreBar({ label, value, max=100, reversed=false }: {
  label: string; value: number; max?: number; reversed?: boolean
}) {
  const pct   = Math.min(100, (Math.abs(value) / max) * 100)
  const good  = reversed ? pct <= 40 : pct >= 65
  const warn  = reversed ? pct <= 60 : pct >= 40
  const color = good ? 'bg-green' : warn ? 'bg-amber' : 'bg-red/60'
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-text3 w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface border border-line/20 overflow-hidden">
        <motion.div className={clsx('h-full rounded-full', color)}
          initial={{ width:0 }} animate={{ width:`${pct}%` }} transition={{ duration:0.8 }} />
      </div>
      <span className="text-[10px] font-mono text-text2 w-8 text-right">{typeof value === 'number' ? value.toFixed(0) : value}</span>
    </div>
  )
}

/* ── Trend direction arrow ────────────────────────────────────── */
function TrendArrow({ direction }: { direction: string | null | undefined }) {
  const d = (direction ?? '').toUpperCase()
  if (d.includes('UP') || d.includes('BULL')) return <ArrowUp size={14} className="text-green" />
  if (d.includes('DOWN') || d.includes('BEAR')) return <ArrowDown size={14} className="text-red" />
  return <Minus size={14} className="text-text3" />
}

/* ── Scan candidate row ───────────────────────────────────────── */
function Candidate({ strategy, signal, confidence }: { strategy: string; signal: string | null; confidence: number }) {
  const up = signal === 'BUY'  || signal === 'CE'
  const dn = signal === 'SELL' || signal === 'PE'
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-line/8 last:border-0">
      <span className="text-[10px] text-text2 font-medium flex-1 min-w-0 truncate">{strategy}</span>
      <div className="flex items-center gap-2 shrink-0">
        <span className={clsx('text-[9px] font-bold px-1.5 py-0.5 rounded',
          up ? 'bg-green/12 text-green' : dn ? 'bg-red/12 text-red' : 'bg-surface text-text3')}>
          {signal ?? '—'}
        </span>
        {confidence > 0 && (
          <span className="text-[9px] font-mono text-text3 w-8 text-right">{confidence.toFixed(0)}%</span>
        )}
      </div>
    </div>
  )
}

export function MarketIntel() {
  const { botStatus, marketState } = useTradingStore()

  const regime    = botStatus?.regime      ?? marketState?.regime
  const engine    = botStatus?.active_engine ?? botStatus?.daily_regime
  const trend     = marketState?.trend_state     ?? botStatus?.trend_state
  const direction = marketState?.trend_direction ?? botStatus?.trend_direction
  const conviction= marketState?.trend_conviction ?? botStatus?.trend_conviction ?? 0
  const vix       = marketState?.regime_vix ?? botStatus?.regime_vix
  const adx       = marketState?.regime_adx ?? botStatus?.regime_adx
  const rsi       = marketState?.regime_rsi ?? botStatus?.regime_rsi
  const atr       = marketState?.regime_atr_ratio ?? botStatus?.regime_atr_ratio
  const impulse   = botStatus?.trend_impulse_grade
  const scores    = marketState?.trend_scores ?? botStatus?.trend_scores ?? {}
  const scan      = botStatus?.last_scan
  const narrative = botStatus?.narrative
  const priority  = marketState?.strategy_priority ?? botStatus?.strategy_priority ?? []

  const regInfo = useMemo(() => classifyRegime(regime), [regime])

  const IMPULSE_CLS: Record<string,string> = {
    A: 'text-green bg-green/10 border-green/25',
    B: 'text-cyan  bg-cyan/10  border-cyan/25',
    C: 'text-text2 bg-surface  border-line/25',
    D: 'text-amber bg-amber/10 border-amber/25',
    F: 'text-red   bg-red/10   border-red/25',
  }

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
            <Brain size={13} className="text-cyan" />
          </div>
          <span className="text-[11px] font-bold uppercase tracking-wider text-text3">Market Intel</span>
        </div>
        <div className="flex items-center gap-1.5">
          {impulse && (
            <span className={clsx('text-[9px] font-black px-2 py-0.5 rounded-md border', IMPULSE_CLS[impulse] ?? 'text-text3 bg-surface border-line/25')}>
              Grade {impulse}
            </span>
          )}
          {regInfo.bullish && (
            <span className="text-[9px] flex items-center gap-1 font-bold px-2 py-0.5 rounded-md bg-green/10 text-green border border-green/25">
              <Flame size={9} /> BULL
            </span>
          )}
        </div>
      </div>

      {/* Regime card — prominent when bullish */}
      <div className={clsx(
        'rounded-xl border px-3 py-2.5 transition-all',
        regInfo.cls,
        regInfo.bullish && 'shadow-lg ' + regInfo.glow,
      )}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[9px] font-bold uppercase tracking-widest opacity-60 mb-0.5">Regime</div>
            <div className="text-[12px] font-black leading-tight">{regInfo.label ?? 'Unknown'}</div>
          </div>
          {regInfo.bullish && <TrendingUp size={18} className="text-green opacity-70" />}
          {engine && (
            <div className="text-right">
              <div className="text-[9px] opacity-60 mb-0.5">Engine</div>
              <div className="text-[10px] font-black">{engine}</div>
            </div>
          )}
        </div>
      </div>

      {/* Trend row */}
      <div className="flex items-center gap-3 bg-surface/50 rounded-xl px-3 py-2">
        <TrendArrow direction={direction} />
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-bold text-text1 truncate">
            {trend ?? direction ?? 'No trend data'}
          </div>
          {direction && trend && (
            <div className="text-[9px] text-text3">{direction}</div>
          )}
        </div>
        {conviction > 0 && (
          <div className="text-right shrink-0">
            <div className="text-[13px] font-black font-mono text-text1">{conviction.toFixed(0)}<span className="text-[9px] text-text3">/100</span></div>
            <div className="text-[9px] text-text3">conviction</div>
          </div>
        )}
      </div>

      {/* Market metrics row */}
      <div className="grid grid-cols-4 gap-1.5">
        {([
          ['VIX',  vix,  vix != null ? (vix < 14 ? 'text-green' : vix > 20 ? 'text-red' : 'text-amber') : 'text-text3'],
          ['ADX',  adx,  adx != null ? (adx > 25 ? 'text-green' : 'text-text2') : 'text-text3'],
          ['RSI',  rsi,  rsi != null ? (rsi > 60 ? 'text-green' : rsi < 40 ? 'text-red' : 'text-text2') : 'text-text3'],
          ['ATR%', atr != null ? (atr*100).toFixed(1) : null, 'text-text2'],
        ] as [string, number | string | null, string][]).map(([lbl, val, cls]) => (
          <div key={lbl} className="text-center bg-surface/60 rounded-xl py-2 border border-line/20">
            <div className={clsx('text-[12px] font-bold font-mono', cls)}>
              {val != null ? (typeof val === 'number' ? val.toFixed(1) : val) : '—'}
            </div>
            <div className="text-[8px] text-text3">{lbl}</div>
          </div>
        ))}
      </div>

      {/* Conviction + score bars */}
      {(Object.keys(scores).length > 0 || conviction > 0) && (
        <div className="space-y-1.5">
          {conviction > 0 && <ScoreBar label="Conviction" value={conviction} />}
          {Object.entries(scores).slice(0, 3).map(([k, v]) => (
            <ScoreBar key={k} label={k.replace(/_/g,' ')} value={v as number} />
          ))}
        </div>
      )}

      {/* Strategy priority */}
      {priority.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {priority.slice(0,5).map((s, i) => (
            <span key={s} className={clsx(
              'text-[9px] px-1.5 py-0.5 rounded border font-mono',
              i === 0 ? 'bg-accent/12 text-accent border-accent/25 font-bold' : 'bg-surface text-text3 border-line/25'
            )}>{i+1}. {s.replace(/_/g,' ')}</span>
          ))}
        </div>
      )}

      {/* Last scan candidates */}
      {scan && scan.candidates && scan.candidates.length > 0 && (
        <div className="border-t border-line/20 pt-2">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Radar size={10} className="text-accent" />
            <span className="text-[9px] font-bold text-text3 uppercase tracking-wide">
              Scan · {scan.strategies_evaluated} strats · {scan.signals_detected} signals
            </span>
          </div>
          <div className="space-y-0">
            {scan.candidates.slice(0,4).map((c, i) => (
              <Candidate key={i} strategy={c.strategy} signal={c.signal} confidence={c.confidence} />
            ))}
          </div>
        </div>
      )}

      {/* Narrative */}
      {narrative && (
        <div className="border-t border-line/20 pt-2">
          <div className="flex items-start gap-1.5">
            <Wind size={10} className="text-text3 mt-0.5 shrink-0" />
            <p className="text-[10px] text-text3 leading-relaxed italic">{narrative}</p>
          </div>
        </div>
      )}

      {/* Bull regime banner */}
      {regInfo.bullish && (
        <div className="rounded-xl bg-green/8 border border-green/20 px-3 py-2 flex items-center gap-2">
          <Shield size={11} className="text-green shrink-0" />
          <p className="text-[10px] text-green font-medium">
            Bull regime active — CE signals preferred. Use ORB / EMA Pullback / VWAP Reclaim strategies.
          </p>
        </div>
      )}
    </div>
  )
}