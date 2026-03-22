import React from 'react'
import clsx from 'clsx'
import { Check, X } from 'lucide-react'

interface FilterState { passed: boolean; value?: any; detail?: string }
interface Props { filters: Record<string, FilterState>; title?: string }

const LABELS: Record<string, string> = {
  orb_range: 'ORB Range', breakout: 'Breakout', candle_body: 'Candle Body',
  volume_surge: 'Volume Surge', vwap: 'VWAP', ema_trend: 'EMA Trend',
  rsi: 'RSI', vix: 'VIX', vwap_cross: 'VWAP Cross',
  rejection_magnitude: 'Rejection', supertrend: 'Supertrend',
}

export function FilterVisualizer({ filters, title = 'Signal Filters' }: Props) {
  const entries = Object.entries(filters)
  const passed  = entries.filter(([, v]) => v.passed).length
  const allPass = passed === entries.length

  return (
    <div className="bg-card rounded-xl border border-line p-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-semibold text-text1">{title}</span>
        <span className={clsx(
          'flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full border',
          allPass
            ? 'bg-greenDim border-green/30 text-green'
            : 'bg-bg border-line text-text3'
        )}>
          {allPass
            ? <span className="w-1.5 h-1.5 rounded-full bg-green inline-block" />
            : <span className="w-1.5 h-1.5 rounded-full bg-text3 inline-block" />}
          {passed}/{entries.length}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {entries.map(([key, state]) => (
          <div
            key={key}
            title={state.detail ?? ''}
            className={clsx(
              'flex items-center gap-2 px-3 py-2 rounded-lg border text-xs',
              state.passed
                ? 'bg-greenDim/60 border-green/20'
                : 'bg-redDim/60 border-red/20'
            )}
          >
            <div className={clsx(
              'flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center',
              state.passed ? 'bg-green/20' : 'bg-red/20'
            )}>
              {state.passed
                ? <Check size={9} className="text-green" strokeWidth={3} />
                : <X size={9} className="text-red" strokeWidth={3} />}
            </div>
            <div className="min-w-0">
              <div className={clsx('font-semibold truncate', state.passed ? 'text-text1' : 'text-text2')}>
                {LABELS[key] ?? key}
              </div>
              {state.value !== undefined && (
                <div className="font-mono text-[10px] text-text3 truncate mt-0.5">
                  {typeof state.value === 'object' ? JSON.stringify(state.value) : String(state.value)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
