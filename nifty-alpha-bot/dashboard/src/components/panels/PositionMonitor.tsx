/**
 * PositionMonitor — shows active position with live P&L visualization.
 * Displayed as a progress bar from entry → SL / entry → target.
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Target, Shield, Clock, Layers, Activity, LogOut, Loader2, CheckCircle2 } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

function PriceBar({
  entry, sl, target, current,
}: { entry: number; sl: number; target: number; current?: number }) {
  // Map everything onto a 0–1 scale from SL to Target
  const range  = target - sl || 1
  const toPos  = (v: number) => Math.max(0, Math.min(1, (v - sl) / range))
  const entryP = toPos(entry)
  const currP  = current != null ? toPos(current) : null
  const pnlPct = current != null ? ((current - entry) / entry) * 100 : null
  const winning = pnlPct != null && pnlPct > 0

  return (
    <div className="space-y-2">
      {/* Bar */}
      <div className="relative h-3 rounded-full bg-surface border border-line/40 overflow-hidden">
        {/* SL zone (red left side) */}
        <div
          className="absolute left-0 top-0 h-full bg-red/15"
          style={{ width: `${entryP * 100}%` }}
        />
        {/* Target zone (green right side) */}
        <div
          className="absolute top-0 h-full bg-green/15"
          style={{ left: `${entryP * 100}%`, right: 0 }}
        />
        {/* Current price marker */}
        {currP != null && (
          <motion.div
            className={clsx(
              'absolute top-0 h-full w-1 rounded-full',
              winning ? 'bg-green' : 'bg-red'
            )}
            style={{ left: `${currP * 100}%` }}
            animate={{ opacity: [0.7, 1, 0.7] }}
            transition={{ repeat: Infinity, duration: 1.5 }}
          />
        )}
        {/* Entry marker */}
        <div
          className="absolute top-0 h-full w-0.5 bg-text2/60"
          style={{ left: `${entryP * 100}%` }}
        />
      </div>
      {/* Labels */}
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-red-l font-bold">SL {sl.toFixed(1)}</span>
        <span className="text-text3">Entry {entry.toFixed(1)}</span>
        <span className="text-green-l font-bold">Tgt {target.toFixed(1)}</span>
      </div>
    </div>
  )
}

function Stat({ label, value, color = 'text-text2' }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <div className="text-center">
      <div className={clsx('text-sm font-bold font-mono', color)}>{value}</div>
      <div className="text-[10px] text-text3 mt-0.5">{label}</div>
    </div>
  )
}

export function PositionMonitor() {
  const { botStatus, position, strategyConfig } = useTradingStore()
  const [closing, setClosing] = useState<'idle'|'loading'|'ok'|'err'>('idle')

  const handleForceClose = async () => {
    if (!window.confirm('Force-close current position at market? This cannot be undone.')) return
    setClosing('loading')
    try {
      await axios.post('/api/bot/force-close')
      setClosing('ok')
      setTimeout(() => setClosing('idle'), 3_000)
    } catch {
      setClosing('err')
      setTimeout(() => setClosing('idle'), 3_000)
    }
  }

  const pos = botStatus?.position ?? position
  const isActive = pos?.state === 'ACTIVE' || botStatus?.state === 'ACTIVE'

  // Derive current option price from position P&L if available
  const entryPx  = pos?.entry_price ?? 0
  const netPnl   = pos?.net_pnl ?? pos?.gross_pnl ?? 0
  const lots     = pos?.lots ?? 1
  const lotSize  = strategyConfig?.nifty_option_lot_size ?? 65  // NIFTY lot size from config
  const currentPx = entryPx && lots
    ? entryPx + netPnl / (lots * lotSize)
    : undefined
  const slmActive = !!((botStatus as any)?.slm_order_active)

  const direction  = (pos?.direction ?? 'CE') as string
  const isCall     = direction.includes('CE') || direction === 'BUY'
  const pnlColor   = netPnl >= 0 ? 'text-green-l' : 'text-red-l'
  const Icon       = isCall ? TrendingUp : TrendingDown

  const strategy   = botStatus?.state === 'ACTIVE'
    ? (pos?.strategy ?? botStatus?.last_scan?.candidates?.[0]?.strategy ?? '—')
    : '—'

  return (
    <div className="glass-card rounded-2xl p-4 h-full flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={clsx(
            'w-7 h-7 rounded-lg flex items-center justify-center',
            isActive ? 'bg-green/15' : 'bg-surface',
          )}>
            <Activity size={13} className={isActive ? 'text-green' : 'text-text3'} />
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Position</span>
        </div>
        <div className={clsx(
          'text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded-md border',
          isActive
            ? 'bg-green/10 border-green/25 text-green'
            : 'bg-surface border-line/30 text-text3'
        )}>
          {isActive ? '⬤ ACTIVE' : '○ IDLE'}
        </div>
      </div>

      <AnimatePresence mode="wait">
        {isActive && pos ? (
          <motion.div
            key="active"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex flex-col gap-4"
          >
            {/* Symbol + direction */}
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Icon size={16} className={isCall ? 'text-green' : 'text-red'} />
                  <span className="text-lg font-black tracking-tight text-text1">
                    {pos.symbol ?? `NIFTY ${pos.strike} ${direction}`}
                  </span>
                </div>
                <div className="text-xs text-text3 mt-0.5 flex items-center gap-2">
                  <span className="bg-accent/15 text-accent-l px-1.5 py-0.5 rounded font-bold">{strategy}</span>
                  <span>{lots} lot{lots !== 1 ? 's' : ''}</span>
                  {pos.entry_time && <span className="flex items-center gap-1"><Clock size={10} />{pos.entry_time}</span>}
                </div>
              </div>
              {/* Live P&L */}
              <motion.div
                key={netPnl.toFixed(0)}
                initial={{ scale: 0.9, opacity: 0.7 }}
                animate={{ scale: 1, opacity: 1 }}
                className={clsx('text-right font-mono')}
              >
                <div className={clsx('text-xl font-black', pnlColor)}>
                  {netPnl >= 0 ? '+' : ''}₹{Math.abs(netPnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                </div>
                <div className="text-[10px] text-text3">Live P&L</div>
              </motion.div>
            </div>

            {/* Price bar */}
            {pos.entry_price && pos.sl_price && pos.target_price && (
              <PriceBar
                entry={pos.entry_price}
                sl={pos.current_sl ?? pos.sl_price}
                target={pos.target_price}
                current={currentPx}
              />
            )}

            {/* Stats row */}
            <div className="grid grid-cols-4 gap-2 bg-surface/50 rounded-xl p-2.5">
              <Stat label="Entry" value={`₹${pos.entry_price?.toFixed(1) ?? '—'}`} />
              <Stat label="SL" value={`₹${(pos.current_sl ?? pos.sl_price)?.toFixed(1) ?? '—'}`} color="text-red-l" />
              <Stat label="Target" value={`₹${pos.target_price?.toFixed(1) ?? '—'}`} color="text-green-l" />
              <Stat
                label="Highest"
                value={pos.highest_price_seen ? `₹${pos.highest_price_seen.toFixed(1)}` : '—'}
                color="text-cyan"
              />
            </div>

            {/* Break-even + SL-M badges */}
            <div className="flex gap-2 flex-wrap">
              {pos.break_even_set && (
                <div className="flex items-center gap-2 text-xs text-cyan bg-cyan/8 border border-cyan/20 rounded-lg px-3 py-1.5">
                  <Shield size={12} /> Break-even activated
                </div>
              )}
              <div className={clsx(
                'flex items-center gap-1.5 text-xs rounded-lg px-3 py-1.5 border',
                slmActive
                  ? 'text-green bg-green/8 border-green/20'
                  : 'text-text3 bg-surface/50 border-line/20'
              )}>
                <Shield size={11} />
                {slmActive ? 'SL-M active at broker' : 'Soft SL (app-managed)'}
              </div>
            </div>

            {/* Manual exit button */}
            <motion.button
              onClick={handleForceClose}
              disabled={closing === 'loading'}
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
              className={clsx(
                'w-full flex items-center justify-center gap-2 py-2 rounded-xl border text-xs font-bold transition-all',
                closing === 'ok'  ? 'bg-green/12 border-green/25 text-green'
                : closing === 'err' ? 'bg-red/12 border-red/25 text-red'
                : 'bg-red/8 border-red/20 text-red hover:bg-red/15'
              )}
            >
              {closing === 'loading' ? <Loader2 size={12} className="animate-spin" /> :
               closing === 'ok'      ? <CheckCircle2 size={12} /> : <LogOut size={12} />}
              {closing === 'loading' ? 'Exiting...' : closing === 'ok' ? 'Exit requested' : closing === 'err' ? 'Failed — retry?' : 'Manual Exit Position'}
            </motion.button>
          </motion.div>
        ) : (
          <motion.div
            key="idle"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex-1 flex flex-col items-center justify-center gap-3 py-4"
          >
            <div className="w-16 h-16 rounded-2xl bg-surface/80 border border-line/30 flex items-center justify-center">
              <Layers size={28} className="text-text3/50" />
            </div>
            <div className="text-center">
              <div className="text-sm font-semibold text-text3">No Active Position</div>
              <div className="text-xs text-text3/60 mt-1">
                {botStatus?.thinking ?? 'Waiting for signal...'}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}