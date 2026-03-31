/**
 * CommandCenter — manual bot controls panel.
 * Every action writes a flag file via API; bot polls those files.
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  Pause, Play, XCircle, AlertTriangle, Settings2, Zap,
  ChevronUp, ChevronDown, RefreshCw, Shield, ToggleLeft, ToggleRight,
  FileText
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

const API = '/api'

type ActionState = 'idle' | 'loading' | 'ok' | 'err'

function useAction() {
  const [state, setState] = useState<ActionState>('idle')
  const run = async (fn: () => Promise<unknown>, confirm?: string) => {
    if (confirm && !window.confirm(confirm)) return
    setState('loading')
    try {
      await fn()
      setState('ok')
      setTimeout(() => setState('idle'), 1800)
    } catch {
      setState('err')
      setTimeout(() => setState('idle'), 2500)
    }
  }
  return { state, run }
}

function Btn({
  label, icon: Icon, onClick, variant = 'default', small = false, disabled = false,
}: {
  label: string; icon: typeof Pause; onClick: () => void
  variant?: 'default' | 'green' | 'red' | 'amber' | 'cyan'
  small?: boolean; disabled?: boolean
}) {
  const colors = {
    default: 'bg-card border-line/40 text-text2 hover:text-text1 hover:border-line',
    green:   'bg-green/10 border-green/30 text-green hover:bg-green/18',
    red:     'bg-red/10 border-red/30 text-red hover:bg-red/18',
    amber:   'bg-amber/10 border-amber/30 text-amber hover:bg-amber/18',
    cyan:    'bg-cyan/10 border-cyan/30 text-cyan hover:bg-cyan/18',
  }
  return (
    <motion.button
      whileHover={{ scale: disabled ? 1 : 1.03 }}
      whileTap={{ scale: disabled ? 1 : 0.96 }}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex items-center gap-2 rounded-xl border font-semibold transition-all',
        small ? 'px-3 py-1.5 text-xs' : 'px-4 py-2.5 text-sm',
        colors[variant],
        disabled && 'opacity-40 cursor-not-allowed',
      )}
    >
      <Icon size={small ? 12 : 14} />
      {label}
    </motion.button>
  )
}

function NumStepper({ label, value, onUp, onDown, min = 1, max = 20 }: {
  label: string; value: number
  onUp: () => void; onDown: () => void
  min?: number; max?: number
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-text3 font-medium">{label}</span>
      <div className="flex items-center gap-1">
        <button onClick={onDown} disabled={value <= min}
          className="w-6 h-6 rounded-lg bg-surface border border-line/40 text-text3 hover:text-text1 flex items-center justify-center disabled:opacity-30">
          <ChevronDown size={12} />
        </button>
        <span className="w-8 text-center text-sm font-bold text-text1 tabular-nums">{value}</span>
        <button onClick={onUp} disabled={value >= max}
          className="w-6 h-6 rounded-lg bg-surface border border-line/40 text-text3 hover:text-text1 flex items-center justify-center disabled:opacity-30">
          <ChevronUp size={12} />
        </button>
      </div>
    </div>
  )
}

export function CommandCenter() {
  const { botStatus, runtimeOverride, setRuntimeOverride, setEmergencyStop } = useTradingStore()
  const pause  = useAction()
  const forceClose = useAction()
  const stop   = useAction()
  const kite   = useAction()

  const isPaused  = botStatus?.paused ?? runtimeOverride.paused ?? false
  const isHalted  = botStatus?.halt_active ?? false
  const hasPos    = botStatus?.state === 'ACTIVE' || botStatus?.position != null
  const paperMode = botStatus?.paper_mode ?? true
  const maxTrades = runtimeOverride.max_trades ?? botStatus?.max_trades ?? 4
  const kiteOk    = botStatus?.kite_connected ?? false

  const patchOverride = async (patch: Record<string, unknown>) => {
    const r = await axios.post(`${API}/bot/override`, patch)
    setRuntimeOverride(r.data.overrides ?? r.data)
  }

  const handlePause = () =>
    pause.run(
      isPaused
        ? () => axios.delete(`${API}/bot/pause`)
        : () => axios.post(`${API}/bot/pause`),
      isPaused ? undefined : 'Pause trading? Bot will not take new entries.'
    )

  const handleStop = () =>
    stop.run(
      isHalted
        ? () => axios.delete(`${API}/emergency-stop`).then(() => setEmergencyStop(false))
        : () => axios.post(`${API}/emergency-stop`).then(() => setEmergencyStop(true)),
      isHalted ? 'Clear emergency halt and resume?' : '⚠️ EMERGENCY STOP — halt all trading NOW?'
    )

  const handleForceClose = () =>
    forceClose.run(
      () => axios.post(`${API}/bot/force-close`),
      'Force-close the current position? Bot will exit immediately at market.'
    )

  const handleKiteRefresh = () =>
    kite.run(() => axios.get(`${API}/kite/verify`))

  const stateColor = (s: ActionState, base: string) =>
    s === 'ok' ? 'text-green' : s === 'err' ? 'text-red' : s === 'loading' ? 'text-amber animate-pulse' : base

  return (
    <div className="glass-card rounded-2xl p-4 h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/15 flex items-center justify-center">
            <Settings2 size={13} className="text-accent-l" />
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Controls</span>
        </div>
        {/* Status badge */}
        <div className={clsx(
          'text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded-md border',
          isHalted ? 'bg-red/15 border-red/30 text-red animate-pulse'
          : isPaused ? 'bg-amber/15 border-amber/30 text-amber'
          : 'bg-green/10 border-green/25 text-green'
        )}>
          {isHalted ? '⚡ HALTED' : isPaused ? '⏸ PAUSED' : '▶ LIVE'}
        </div>
      </div>

      {/* Primary actions */}
      <div className="grid grid-cols-2 gap-2">
        <Btn
          label={isPaused ? 'Resume' : 'Pause'}
          icon={isPaused ? Play : Pause}
          onClick={handlePause}
          variant={isPaused ? 'green' : 'amber'}
          disabled={isHalted || pause.state === 'loading'}
        />
        <Btn
          label={isHalted ? 'Clear Halt' : 'E-STOP'}
          icon={isHalted ? Shield : AlertTriangle}
          onClick={handleStop}
          variant={isHalted ? 'green' : 'red'}
          disabled={stop.state === 'loading'}
        />
      </div>

      {/* Force close (only when position active) */}
      <AnimatePresence>
        {hasPos && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <Btn
              label="Force Close Position"
              icon={XCircle}
              onClick={handleForceClose}
              variant="red"
              disabled={forceClose.state === 'loading'}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="border-t border-line/30 pt-3 space-y-3">
        {/* Max trades stepper */}
        <NumStepper
          label="Max Trades / Day"
          value={maxTrades}
          onUp={() => patchOverride({ max_trades: maxTrades + 1 })}
          onDown={() => patchOverride({ max_trades: Math.max(1, maxTrades - 1) })}
          min={1} max={10}
        />

        {/* Paper mode toggle */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-text3 font-medium">Paper Mode</span>
          <button
            onClick={() => patchOverride({ paper_mode: !paperMode })}
            className={clsx('flex items-center gap-1.5 text-xs font-bold transition-all',
              paperMode ? 'text-amber' : 'text-green'
            )}
          >
            {paperMode ? <ToggleLeft size={18} /> : <ToggleRight size={18} />}
            {paperMode ? 'ON (Paper)' : 'OFF (Live!)'}
          </button>
        </div>

        {/* Kite connection */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className={clsx('w-1.5 h-1.5 rounded-full', kiteOk ? 'bg-green' : 'bg-red')} />
            <span className="text-xs text-text3">{kiteOk ? 'Kite Connected' : 'Kite Offline'}</span>
          </div>
          <button
            onClick={handleKiteRefresh}
            disabled={kite.state === 'loading'}
            className={clsx('flex items-center gap-1.5 text-[11px] font-semibold px-2 py-1 rounded-lg border',
              'border-line/30 text-text3 hover:text-text2 hover:border-line transition-all',
              kite.state === 'loading' && 'animate-pulse'
            )}
          >
            <RefreshCw size={10} className={kite.state === 'loading' ? 'animate-spin' : ''} />
            {kite.state === 'ok' ? 'Verified ✓' : kite.state === 'err' ? 'Failed ✗' : 'Verify'}
          </button>
        </div>
      </div>

      {/* Kite auth quick link */}
      {!kiteOk && (
        <a
          href="#"
          onClick={e => { e.preventDefault(); window.open('/api/kite/auth-url', '_blank') }}
          className="flex items-center gap-2 text-xs text-cyan hover:text-cyan font-semibold py-2 px-3 rounded-xl border border-cyan/20 bg-cyan/5 hover:bg-cyan/10 transition-all"
        >
          <Zap size={12} />
          Login with Kite
        </a>
      )}

      {/* Action feedback */}
      <AnimatePresence>
        {(pause.state !== 'idle' || forceClose.state !== 'idle' || stop.state !== 'idle') && (
          <motion.div
            initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}
            className={clsx('text-xs font-semibold text-center py-1.5 rounded-lg',
              (pause.state === 'ok' || forceClose.state === 'ok' || stop.state === 'ok')
                ? 'bg-green/10 text-green' : 'bg-red/10 text-red'
            )}
          >
            {pause.state === 'ok' && (isPaused ? '▶ Resumed' : '⏸ Paused')}
            {pause.state === 'err' && '⚠ Action failed'}
            {forceClose.state === 'ok' && '✓ Close requested'}
            {stop.state === 'ok' && (isHalted ? '✓ Halt cleared' : '⚡ HALTED')}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}