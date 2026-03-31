/**
 * MarketIntel — regime, trend, signal quality, and scan summary.
 * Shows the bot's current market read in a visual format.
 */
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { Brain, Radar, BarChart3, Wind, ArrowUp, ArrowDown, Minus } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

const REGIME_COLORS: Record<string, string> = {
  STRONG_TREND_UP:   'text-green  bg-green/10  border-green/25',
  TREND_UP:          'text-green  bg-green/8   border-green/20',
  STRONG_TREND_DOWN: 'text-red    bg-red/10    border-red/25',
  TREND_DOWN:        'text-red    bg-red/8     border-red/20',
  SIDEWAYS:          'text-text2  bg-surface   border-line/30',
  HIGH_VOL:          'text-amber  bg-amber/10  border-amber/25',
  UNKNOWN:           'text-text3  bg-surface   border-line/20',
}

const IMPULSE_COLORS: Record<string, string> = {
  A: 'text-green  bg-green/10',
  B: 'text-cyan   bg-cyan/10',
  C: 'text-text2  bg-surface',
  D: 'text-amber  bg-amber/10',
  F: 'text-red    bg-red/10',
}

function regimeClass(regime: string | null | undefined): string {
  if (!regime) return REGIME_COLORS.UNKNOWN
  for (const key of Object.keys(REGIME_COLORS)) {
    if (regime.toUpperCase().includes(key)) return REGIME_COLORS[key]
  }
  return REGIME_COLORS.UNKNOWN
}

function ScoreBar({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100)
  const color = pct >= 70 ? 'bg-green' : pct >= 45 ? 'bg-amber' : 'bg-red/70'
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-text3 w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface border border-line/30 overflow-hidden">
        <motion.div
          className={clsx('h-full rounded-full', color)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </div>
      <span className="text-[10px] font-mono text-text2 w-6 text-right">{Math.round(value)}</span>
    </div>
  )
}

function TrendArrow({ direction }: { direction: string | null | undefined }) {
  if (!direction) return <Minus size={14} className="text-text3" />
  const up = direction.toUpperCase().includes('UP') || direction.toUpperCase().includes('BULL')
  const dn = direction.toUpperCase().includes('DOWN') || direction.toUpperCase().includes('BEAR')
  if (up) return <ArrowUp size={14} className="text-green" />
  if (dn) return <ArrowDown size={14} className="text-red" />
  return <Minus size={14} className="text-text3" />
}

export function MarketIntel() {
  const { botStatus, marketState } = useTradingStore()

  const regime     = botStatus?.regime ?? marketState?.regime
  const engine     = botStatus?.active_engine ?? botStatus?.daily_regime
  const trend      = marketState?.trend_state ?? botStatus?.trend_state
  const direction  = marketState?.trend_direction ?? botStatus?.trend_direction
  const conviction = marketState?.trend_conviction ?? botStatus?.trend_conviction ?? 0
  const vix        = marketState?.regime_vix ?? botStatus?.regime_vix
  const adx        = marketState?.regime_adx ?? botStatus?.regime_adx
  const rsi        = marketState?.regime_rsi ?? botStatus?.regime_rsi
  const atr        = marketState?.regime_atr_ratio ?? botStatus?.regime_atr_ratio
  const impulse    = botStatus?.trend_impulse_grade
  const scores     = marketState?.trend_scores ?? botStatus?.trend_scores ?? {}
  const scan       = botStatus?.last_scan
  const narrative  = botStatus?.narrative

  const regCls = regimeClass(regime)

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
            <Brain size={13} className="text-cyan" />
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Market Intelligence</span>
        </div>
        {impulse && (
          <div className={clsx('text-[10px] font-black px-2 py-0.5 rounded-md', IMPULSE_COLORS[impulse] ?? 'text-text3 bg-surface')}>
            Grade {impulse}
          </div>
        )}
      </div>

      {/* Regime + Engine row */}
      <div className="grid grid-cols-2 gap-2">
        <div className={clsx('rounded-xl border px-3 py-2', regCls)}>
          <div className="text-[9px] font-bold uppercase tracking-widest opacity-70 mb-0.5">Regime</div>
          <div className="text-xs font-black leading-tight">{regime ?? 'Unknown'}</div>
        </div>
        <div className="rounded-xl border border-accent/20 bg-accent/8 px-3 py-2">
          <div className="text-[9px] font-bold uppercase tracking-widest text-accent-l/70 mb-0.5">Engine</div>
          <div className="text-xs font-black text-accent-l leading-tight">{engine ?? '—'}</div>
        </div>
      </div>

      {/* Trend row */}
      <div className="flex items-center gap-3 bg-surface/50 rounded-xl px-3 py-2">
        <TrendArrow direction={direction} />
        <div className="flex-1">
          <div className="text-xs font-bold text-text1">
            {trend ?? 'No Trend Data'}
          </div>
          {direction && (
            <div className="text-[10px] text-text3">{direction}</div>
          )}
        </div>
        {conviction > 0 && (
          <div className="text-right">
            <div className="text-sm font-black font-mono text-text1">{conviction.toFixed(0)}<span className="text-xs text-text3">/100</span></div>
            <div className="text-[9px] text-text3">conviction</div>
          </div>
        )}
      </div>

      {/* Market metrics */}
      <div className="grid grid-cols-4 gap-2">
        {[['VIX', vix, vix != null && vix > 18 ? 'text-amber' : 'text-text2'],
          ['ADX', adx, adx != null && adx > 25 ? 'text-green' : 'text-text2'],
          ['RSI', rsi, 'text-text2'],
          ['ATR%', atr != null ? (atr * 100).toFixed(1) : null, 'text-text2'],
        ].map(([label, value, color]) => (
          <div key={label as string} className="text-center bg-surface/50 rounded-xl py-2">
            <div className={clsx('text-sm font-bold font-mono', color)}>
              {value != null ? Number(value).toFixed(1) : '—'}
            </div>
            <div className="text-[9px] text-text3">{label}</div>
          </div>
        ))}
      </div>

      {/* Score bars (from trend_scores) */}
      {Object.keys(scores).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(scores).slice(0, 4).map(([k, v]) => (
            <ScoreBar key={k} label={k.replace(/_/g, ' ')} value={v as number} />
          ))}
        </div>
      )}

      {/* Scan summary */}
      {scan && (
        <div className="border-t border-line/25 pt-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Radar size={11} className="text-accent-l" />
            <span className="text-[10px] font-bold text-text3 uppercase tracking-wide">
              Last Scan · {scan.strategies_evaluated} strategies · {scan.signals_detected} signals
            </span>
          </div>
          {scan.candidates?.slice(0, 3).map((c, i) => (
            <div key={i} className="flex items-center justify-between py-1">
              <span className="text-xs text-text2 font-medium">{c.strategy}</span>
              <div className="flex items-center gap-2">
                <span className={clsx('text-[10px] font-bold', c.signal === 'BUY' ? 'text-green' : c.signal === 'SELL' ? 'text-red' : 'text-text3')}>
                  {c.signal}
                </span>
                {c.confidence > 0 && (
                  <span className="text-[10px] font-mono text-text3">{c.confidence.toFixed(0)}%</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Narrative */}
      {narrative && (
        <div className="border-t border-line/25 pt-2">
          <div className="flex items-start gap-1.5">
            <Wind size={11} className="text-text3 mt-0.5 shrink-0" />
            <p className="text-[11px] text-text3 leading-relaxed italic">{narrative}</p>
          </div>
        </div>
      )}
    </div>
  )
}