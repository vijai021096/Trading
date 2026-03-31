/**
 * RiskPanel — drawdown gauge, consecutive losses, daily loss limit progress.
 */
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { ShieldAlert, Gauge, TrendingDown, Layers } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

function ProgressBar({ value, max, color, label, sublabel }: {
  value: number; max: number; color: string; label: string; sublabel?: string
}) {
  const pct = Math.min(100, (value / max) * 100)
  const danger = pct >= 75
  const warn   = pct >= 50
  const barColor = danger ? 'bg-red' : warn ? 'bg-amber' : color

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-[10px]">
        <span className="text-text3 font-medium">{label}</span>
        <span className={clsx('font-bold font-mono',
          danger ? 'text-red' : warn ? 'text-amber' : 'text-text2'
        )}>
          {typeof value === 'number' ? value.toFixed(1) : value}/{max}{sublabel}
        </span>
      </div>
      <div className="h-2 rounded-full bg-surface border border-line/30 overflow-hidden">
        <motion.div
          className={clsx('h-full rounded-full', barColor)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}

function RiskBadge({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className={clsx(
      'flex flex-col items-center gap-0.5 rounded-xl border px-3 py-2',
      ok ? 'bg-green/8 border-green/20' : 'bg-red/8 border-red/20'
    )}>
      <span className={clsx('text-sm font-black font-mono', ok ? 'text-green' : 'text-red')}>{value}</span>
      <span className="text-[9px] text-text3">{label}</span>
    </div>
  )
}

export function RiskPanel() {
  const { botStatus, strategyConfig } = useTradingStore()

  const drawPct     = botStatus?.drawdown_pct ?? 0
  const maxDraw     = botStatus?.max_drawdown_pct ?? strategyConfig?.max_drawdown_pct ?? 15
  const dailyLoss   = Math.abs(Math.min(0, botStatus?.daily_pnl ?? 0))
  const capital     = botStatus?.current_capital ?? botStatus?.starting_capital ?? 100_000
  const maxDailyLoss = botStatus?.max_daily_loss_pct ?? strategyConfig?.max_daily_loss_pct ?? 3
  const maxDailyLossAmt = (maxDailyLoss / 100) * (botStatus?.starting_capital ?? 100_000)
  const consLoss    = botStatus?.consecutive_losses ?? 0
  const riskPerTrade = botStatus?.risk_per_trade_pct ?? strategyConfig?.risk_per_trade_pct ?? 1.5
  const peakCap     = botStatus?.peak_capital ?? capital

  const safeDrawdown = drawPct < maxDraw * 0.5
  const safeDailyLoss = dailyLoss < maxDailyLossAmt * 0.5
  const safeConsLoss  = consLoss < 3

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-red/10 flex items-center justify-center">
          <ShieldAlert size={13} className="text-red-l" />
        </div>
        <span className="text-xs font-bold uppercase tracking-widest text-text3">Risk Monitor</span>
      </div>

      {/* Risk badges */}
      <div className="grid grid-cols-3 gap-2">
        <RiskBadge label="Drawdown" value={`${drawPct.toFixed(1)}%`} ok={safeDrawdown} />
        <RiskBadge label="Con. Losses" value={`${consLoss}`} ok={safeConsLoss} />
        <RiskBadge label="Risk/Trade" value={`${riskPerTrade}%`} ok={true} />
      </div>

      {/* Progress bars */}
      <div className="space-y-3">
        <ProgressBar
          label="Drawdown vs Max"
          value={drawPct}
          max={maxDraw}
          color="bg-cyan"
          sublabel="%"
        />
        <ProgressBar
          label="Daily Loss vs Limit"
          value={dailyLoss}
          max={maxDailyLossAmt}
          color="bg-accent"
          sublabel="₹"
        />
      </div>

      {/* Capital row */}
      <div className="grid grid-cols-2 gap-2 bg-surface/50 rounded-xl p-2.5">
        <div className="text-center">
          <div className="text-sm font-bold font-mono text-text1">
            ₹{Math.round(capital / 1000)}k
          </div>
          <div className="text-[9px] text-text3">Current Capital</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-bold font-mono text-text1">
            ₹{Math.round(peakCap / 1000)}k
          </div>
          <div className="text-[9px] text-text3">Peak Capital</div>
        </div>
      </div>

      {/* Halt / pause warnings */}
      {(botStatus?.halt_active || botStatus?.paused) && (
        <div className={clsx(
          'flex items-center gap-2 text-xs font-bold px-3 py-2 rounded-xl border animate-pulse',
          botStatus.halt_active
            ? 'bg-red/10 border-red/30 text-red'
            : 'bg-amber/10 border-amber/30 text-amber'
        )}>
          <ShieldAlert size={13} />
          {botStatus.halt_active ? 'EMERGENCY HALT ACTIVE' : 'Trading Paused'}
        </div>
      )}
    </div>
  )
}