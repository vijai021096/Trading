/**
 * RiskPanel — Tri-gate risk monitor:
 *   Gate 1: Drawdown from peak (primary halt at 20%)
 *   Gate 2: Daily loss % soft stop (4%)
 *   Gate 3: Daily loss hard ₹ floor (₹8k absolute)
 *   Info:   Consecutive losses (informational, NOT a hard stop)
 *
 * BUG FIX: max_daily_loss_pct from API is already a decimal (0.04),
 * do NOT divide by 100 again — that made the limit show as ₹40 instead of ₹4,000!
 */
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { ShieldAlert, ShieldCheck, TrendingDown, Zap, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

function GaugeBar({
  value, max, label, valueFmt, maxFmt, danger = 75, warn = 50,
}: {
  value: number; max: number; label: string
  valueFmt: string; maxFmt: string
  danger?: number; warn?: number
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  const isDanger = pct >= danger
  const isWarn   = pct >= warn
  const barColor = isDanger ? 'bg-red' : isWarn ? 'bg-amber' : 'bg-cyan'
  const textColor = isDanger ? 'text-red' : isWarn ? 'text-amber' : 'text-cyan'

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-[10px]">
        <span className="text-text3 font-medium">{label}</span>
        <span className={clsx('font-bold font-mono', textColor)}>
          {valueFmt}
          <span className="text-text3 font-normal"> / {maxFmt}</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-surface border border-line/20 overflow-hidden">
        <motion.div
          className={clsx('h-full rounded-full transition-colors', barColor)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </div>
      <div className="flex justify-end">
        <span className={clsx('text-[9px] font-mono font-bold', textColor)}>
          {pct.toFixed(1)}% used
        </span>
      </div>
    </div>
  )
}

function MiniStat({
  label, value, sub, color = 'text-text1', bg = 'bg-surface/50',
}: {
  label: string; value: string; sub?: string
  color?: string; bg?: string
}) {
  return (
    <div className={clsx('rounded-xl p-2.5 text-center border border-line/15', bg)}>
      <div className={clsx('text-sm font-black font-mono', color)}>{value}</div>
      <div className="text-[9px] text-text3 mt-0.5 leading-tight">{label}</div>
      {sub && <div className="text-[9px] font-bold text-text3/60 mt-0.5">{sub}</div>}
    </div>
  )
}

export function RiskPanel() {
  const { botStatus, strategyConfig } = useTradingStore()

  // ── Values from store ────────────────────────────────────────────
  const capital      = botStatus?.starting_capital ?? strategyConfig?.capital ?? 100_000
  const currentCap   = botStatus?.current_capital ?? capital
  const peakCap      = botStatus?.peak_capital ?? currentCap
  const drawPct      = botStatus?.drawdown_pct ?? 0
  const maxDrawPct   = botStatus?.max_drawdown_pct ?? strategyConfig?.max_drawdown_pct ?? 20

  // FIXED: max_daily_loss_pct is a decimal (0.04), NOT a percentage integer!
  // Do NOT divide by 100 — it's already the fraction.
  const dailyLossPctDecimal = botStatus?.max_daily_loss_pct ?? strategyConfig?.max_daily_loss_pct ?? 0.04
  const dailyLossSoftLimit  = dailyLossPctDecimal * capital          // e.g. 0.04 * 1L = ₹4,000
  const dailyLossHardLimit  = strategyConfig?.max_daily_loss_hard ?? 8_000

  const dailyPnl     = botStatus?.daily_pnl ?? 0
  const dailyLossUsed = Math.abs(Math.min(0, dailyPnl))              // always positive

  const consLoss     = botStatus?.consecutive_losses ?? 0
  const riskPerTrade = botStatus?.risk_per_trade_pct ?? strategyConfig?.risk_per_trade_pct ?? 0.02
  const riskPerTradePct = riskPerTrade < 1 ? riskPerTrade * 100 : riskPerTrade  // normalise to %

  const isHalted     = botStatus?.halt_active ?? false
  const isPaused     = botStatus?.paused ?? false

  // ── Safety grades ────────────────────────────────────────────────
  const drawSafe      = drawPct < maxDrawPct * 0.5
  const dailySafe     = dailyLossUsed < dailyLossSoftLimit * 0.5
  const consOk        = consLoss < 4
  const allGood       = !isHalted && !isPaused && drawSafe && dailySafe

  const fmtINR = (n: number) =>
    `₹${Math.round(n).toLocaleString('en-IN')}`

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-3.5 border border-line/20">

      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={clsx(
            'w-7 h-7 rounded-lg flex items-center justify-center',
            isHalted ? 'bg-red/15' : allGood ? 'bg-green/10' : 'bg-amber/10',
          )}>
            {isHalted
              ? <ShieldAlert size={13} className="text-red" />
              : allGood
                ? <ShieldCheck size={13} className="text-green" />
                : <AlertTriangle size={13} className="text-amber" />}
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Risk Monitor</span>
        </div>
        <div className={clsx(
          'flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider border',
          isHalted  ? 'bg-red/10 border-red/25 text-red animate-pulse'
          : isPaused ? 'bg-amber/10 border-amber/25 text-amber'
          : allGood  ? 'bg-green/8 border-green/20 text-green'
          :             'bg-amber/8 border-amber/20 text-amber',
        )}>
          <div className={clsx('w-1.5 h-1.5 rounded-full',
            isHalted ? 'bg-red' : isPaused ? 'bg-amber' : allGood ? 'bg-green' : 'bg-amber'
          )} />
          {isHalted ? 'HALTED' : isPaused ? 'PAUSED' : allGood ? 'SAFE' : 'CAUTION'}
        </div>
      </div>

      {/* ── Capital snapshot ──────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-2">
        <MiniStat
          label="Current"
          value={currentCap >= 1000 ? `₹${(currentCap/1000).toFixed(1)}k` : fmtINR(currentCap)}
          sub={currentCap >= capital ? '↑ growing' : '↓ below start'}
          color={currentCap >= capital ? 'text-green' : 'text-red'}
          bg={currentCap >= capital ? 'bg-green/5' : 'bg-red/5'}
        />
        <MiniStat
          label="Peak"
          value={peakCap >= 1000 ? `₹${(peakCap/1000).toFixed(1)}k` : fmtINR(peakCap)}
          color="text-accent"
          bg="bg-accent/5"
        />
        <MiniStat
          label="Risk/Trade"
          value={`${riskPerTradePct.toFixed(1)}%`}
          sub={fmtINR(capital * (riskPerTradePct / 100))}
          color="text-cyan"
          bg="bg-cyan/5"
        />
      </div>

      {/* ── Risk gates ────────────────────────────────────────── */}
      <div className="space-y-3 bg-surface/30 rounded-xl p-3 border border-line/10">
        <div className="text-[9px] font-bold text-text3 uppercase tracking-widest flex items-center gap-1.5">
          <Zap size={9} className="text-accent" /> Circuit Breakers
        </div>

        {/* Gate 1: Drawdown from peak (primary halt) */}
        <GaugeBar
          label="Drawdown from peak (primary halt)"
          value={drawPct}
          max={maxDrawPct}
          valueFmt={`${drawPct.toFixed(1)}%`}
          maxFmt={`${maxDrawPct}%`}
          danger={80} warn={50}
        />

        {/* Gate 2: Daily loss soft stop */}
        <GaugeBar
          label={`Daily loss — soft stop (${(dailyLossPctDecimal * 100).toFixed(0)}% = ${fmtINR(dailyLossSoftLimit)})`}
          value={dailyLossUsed}
          max={dailyLossSoftLimit}
          valueFmt={fmtINR(dailyLossUsed)}
          maxFmt={fmtINR(dailyLossSoftLimit)}
          danger={75} warn={45}
        />

        {/* Gate 3: Hard ₹ floor */}
        <GaugeBar
          label="Hard ₹ floor (absolute max loss)"
          value={dailyLossUsed}
          max={dailyLossHardLimit}
          valueFmt={fmtINR(dailyLossUsed)}
          maxFmt={fmtINR(dailyLossHardLimit)}
          danger={80} warn={55}
        />
      </div>

      {/* ── Consecutive losses — INFORMATIONAL ────────────────── */}
      <div className={clsx(
        'flex items-center justify-between rounded-xl px-3 py-2.5 border',
        consOk ? 'bg-surface/40 border-line/15' : 'bg-amber/5 border-amber/20',
      )}>
        <div className="flex items-center gap-2">
          <TrendingDown size={11} className={consOk ? 'text-text3' : 'text-amber'} />
          <div>
            <div className={clsx('text-[11px] font-bold font-mono', consOk ? 'text-text2' : 'text-amber')}>
              {consLoss} consecutive loss{consLoss !== 1 ? 'es' : ''}
            </div>
            <div className="text-[9px] text-text3">ℹ️ info-only — drawdown is the real gate</div>
          </div>
        </div>
        <div className={clsx(
          'text-[9px] font-black px-2 py-1 rounded-lg border',
          consOk ? 'bg-surface border-line/20 text-text3' : 'bg-amber/10 border-amber/25 text-amber',
        )}>
          {consLoss === 0 ? 'CLEAN' : consLoss < 4 ? 'NORMAL' : consLoss < 7 ? 'ROUGH' : 'TOUGH'}
        </div>
      </div>

      {/* ── Daily P&L summary ─────────────────────────────────── */}
      <div className={clsx(
        'flex items-center justify-between rounded-xl px-3 py-2 border',
        dailyPnl > 0 ? 'bg-green/5 border-green/15'
        : dailyPnl < -dailyLossSoftLimit * 0.5 ? 'bg-red/5 border-red/15'
        : 'bg-surface/40 border-line/15',
      )}>
        <span className="text-[10px] text-text3">Today's P&L</span>
        <span className={clsx(
          'text-sm font-black font-mono',
          dailyPnl > 0 ? 'text-green' : dailyPnl < 0 ? 'text-red' : 'text-text2',
        )}>
          {dailyPnl >= 0 ? '+' : ''}{fmtINR(dailyPnl)}
        </span>
      </div>

      {/* ── HALTED / PAUSED banner ─────────────────────────────── */}
      {(isHalted || isPaused) && (
        <div className={clsx(
          'flex items-center gap-2 text-xs font-bold px-3 py-2.5 rounded-xl border animate-pulse',
          isHalted
            ? 'bg-red/10 border-red/30 text-red'
            : 'bg-amber/10 border-amber/30 text-amber',
        )}>
          <ShieldAlert size={13} />
          {isHalted
            ? `🚨 EMERGENCY HALT — ${botStatus?.halt_reason ?? 'risk limit breached'}`
            : '⏸ Trading is currently paused'}
        </div>
      )}

      {/* ── All-clear row ─────────────────────────────────────── */}
      {allGood && (
        <div className="flex items-center gap-1.5 text-[10px] text-green/70 font-medium">
          <CheckCircle2 size={11} className="text-green" />
          All risk gates clear — your capital is protected 💚
        </div>
      )}
    </div>
  )
}
