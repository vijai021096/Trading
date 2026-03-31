/**
 * CommandCenter — bot controls with:
 *   • Pause / E-Stop / Force-Close
 *   • VIX max override (war-era default: 28)
 *   • Max trades / lots stepper
 *   • Strategy filter (ALL / CE only / PE only)
 *   • Manual entry signal queue
 *   • Manual position exit
 */
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import clsx from 'clsx'
import {
  Pause, Play, XCircle, AlertTriangle, Settings2, Zap,
  ChevronUp, ChevronDown, RefreshCw, Shield, ToggleLeft, ToggleRight,
  TrendingUp, TrendingDown, Gauge, Flame, Filter, LogIn, LogOut,
  CheckCircle2, AlertCircle,
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

const API = '/api'
type AS = 'idle' | 'loading' | 'ok' | 'err'

function useAction() {
  const [state, setState] = useState<AS>('idle')
  const run = async (fn: () => Promise<unknown>, confirmMsg?: string) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setState('loading')
    try { await fn(); setState('ok'); setTimeout(() => setState('idle'), 2_000) }
    catch  { setState('err'); setTimeout(() => setState('idle'), 3_000) }
  }
  return { state, run, loading: state === 'loading', ok: state === 'ok', err: state === 'err' }
}

/* ── Pill button ──────────────────────────────────────────────── */
type BtnVariant = 'default'|'green'|'red'|'amber'|'cyan'|'accent'
function Btn({
  label, icon: Icon, onClick, variant='default', small=false, disabled=false, fullWidth=false
}: {
  label: string; icon: typeof Pause; onClick: () => void
  variant?: BtnVariant; small?: boolean; disabled?: boolean; fullWidth?: boolean
}) {
  const cls: Record<BtnVariant,string> = {
    default:'bg-card   border-line/40  text-text2  hover:text-text1 hover:border-line',
    green:  'bg-green/10 border-green/30  text-green  hover:bg-green/18',
    red:    'bg-red/10   border-red/30    text-red    hover:bg-red/18',
    amber:  'bg-amber/10 border-amber/30  text-amber  hover:bg-amber/18',
    cyan:   'bg-cyan/10  border-cyan/30   text-cyan   hover:bg-cyan/18',
    accent: 'bg-accent/10 border-accent/30 text-accent hover:bg-accent/18',
  }
  return (
    <motion.button whileHover={{ scale: disabled ? 1 : 1.02 }} whileTap={{ scale: disabled ? 1 : 0.96 }}
      onClick={onClick} disabled={disabled}
      className={clsx(
        'flex items-center justify-center gap-2 rounded-xl border font-semibold transition-all',
        small ? 'px-2.5 py-1.5 text-[11px]' : 'px-3 py-2 text-xs',
        cls[variant], fullWidth && 'w-full',
        disabled && 'opacity-40 cursor-not-allowed',
      )}>
      <Icon size={small ? 11 : 13} />{label}
    </motion.button>
  )
}

/* ── Number stepper ───────────────────────────────────────────── */
function Stepper({ label, value, onUp, onDown, min=1, max=20, suffix='' }: {
  label: string; value: number; onUp: ()=>void; onDown: ()=>void
  min?: number; max?: number; suffix?: string
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-text3">{label}</span>
      <div className="flex items-center gap-1">
        <button onClick={onDown} disabled={value <= min}
          className="w-6 h-6 rounded-lg bg-surface border border-line/40 text-text3 hover:text-text1 flex items-center justify-center disabled:opacity-30">
          <ChevronDown size={11} />
        </button>
        <span className="w-12 text-center text-[12px] font-bold text-text1 font-mono">{value}{suffix}</span>
        <button onClick={onUp} disabled={value >= max}
          className="w-6 h-6 rounded-lg bg-surface border border-line/40 text-text3 hover:text-text1 flex items-center justify-center disabled:opacity-30">
          <ChevronUp size={11} />
        </button>
      </div>
    </div>
  )
}

/* ── VIX preset chips ─────────────────────────────────────────── */
const VIX_PRESETS = [
  { label: 'Normal', val: 18, color: 'text-green border-green/25 bg-green/8' },
  { label: 'Elev.',  val: 22, color: 'text-cyan  border-cyan/25  bg-cyan/8'  },
  { label: 'High',   val: 25, color: 'text-amber border-amber/25 bg-amber/8' },
  { label: 'War',    val: 30, color: 'text-red   border-red/25   bg-red/8'   },
]

/* ── Manual entry form ────────────────────────────────────────── */
function ManualEntryPanel({ onClose }: { onClose: () => void }) {
  const { botStatus } = useTradingStore()
  const [dir, setDir]         = useState<'CE'|'PE'>('CE')
  const [strategy, setStrategy] = useState('MANUAL')
  const [lots, setLots]         = useState(1)
  const [note, setNote]         = useState('')
  const [pending, setPending]   = useState(false)
  const [result, setResult]     = useState<'ok'|'err'|null>(null)
  const [hasPending, setHasPending] = useState(false)

  useEffect(() => {
    axios.get(`${API}/bot/manual-signal`).then(r => setHasPending(r.data.pending)).catch(() => {})
  }, [])

  const isActive = botStatus?.position?.state === 'ACTIVE' || botStatus?.state === 'ACTIVE'

  const submit = async () => {
    if (isActive) { window.alert('Close current position first!'); return }
    if (!window.confirm(`Queue manual ${dir} entry signal? Bot will take this on next scan cycle.`)) return
    setPending(true)
    try {
      await axios.post(`${API}/bot/manual-signal`, { direction: dir, strategy, lots, note })
      setResult('ok'); setHasPending(true)
    } catch (e: any) {
      setResult('err'); window.alert(e.response?.data?.detail || 'Signal failed')
    } finally { setPending(false) }
  }

  const cancel = async () => {
    await axios.delete(`${API}/bot/manual-signal`).catch(() => {})
    setHasPending(false); setResult(null)
  }

  return (
    <motion.div initial={{ opacity:0, height:0 }} animate={{ opacity:1, height:'auto' }}
      exit={{ opacity:0, height:0 }} className="overflow-hidden">
      <div className="mt-2 p-3 rounded-xl bg-surface/70 border border-accent/20 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold text-accent">Manual Entry Signal</span>
          <button onClick={onClose} className="text-text3 hover:text-text1 text-[10px]">✕ close</button>
        </div>

        {isActive && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-amber/8 border border-amber/20 text-[10px] text-amber">
            <AlertCircle size={10} /> Position active — close it before queuing entry
          </div>
        )}

        {hasPending && (
          <div className="flex items-center justify-between p-2 rounded-lg bg-green/8 border border-green/20 text-[10px] text-green">
            <span><CheckCircle2 size={10} className="inline mr-1" />Signal queued — waiting for next scan</span>
            <button onClick={cancel} className="text-red hover:text-red/80 font-bold">cancel</button>
          </div>
        )}

        {!hasPending && (
          <>
            {/* Direction */}
            <div className="flex gap-2">
              {(['CE','PE'] as const).map(d => (
                <button key={d} onClick={() => setDir(d)}
                  className={clsx(
                    'flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl border text-[11px] font-bold transition-all',
                    dir === d
                      ? d === 'CE' ? 'bg-green/15 border-green/30 text-green' : 'bg-red/15 border-red/30 text-red'
                      : 'bg-surface border-line/30 text-text3 hover:border-accent/30'
                  )}>
                  {d === 'CE' ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                  {d}
                </button>
              ))}
            </div>

            {/* Strategy label */}
            <div>
              <label className="text-[10px] text-text3 mb-1 block">Strategy Label</label>
              <select value={strategy} onChange={e => setStrategy(e.target.value)}
                className="w-full bg-bg border border-line/30 rounded-lg px-2 py-1.5 text-[11px] text-text1 focus:outline-none focus:border-accent/40">
                <option value="MANUAL">MANUAL</option>
                <option value="ORB">ORB</option>
                <option value="EMA_PULLBACK">EMA_PULLBACK</option>
                <option value="VWAP_RECLAIM">VWAP_RECLAIM</option>
                <option value="MOMENTUM">MOMENTUM</option>
              </select>
            </div>

            {/* Lots */}
            <Stepper label="Lots" value={lots} onUp={() => setLots(l => Math.min(l+1,5))}
              onDown={() => setLots(l => Math.max(l-1,1))} min={1} max={5} />

            {/* Note */}
            <input value={note} onChange={e => setNote(e.target.value)}
              placeholder="Note (optional)..."
              className="w-full bg-bg border border-line/30 rounded-lg px-2 py-1.5 text-[10px] text-text1 placeholder:text-text3/50 focus:outline-none focus:border-accent/40" />

            <Btn label={pending ? 'Queueing...' : `Queue ${dir} Signal`}
              icon={LogIn} onClick={submit} variant="accent"
              disabled={pending || isActive} fullWidth />
          </>
        )}
      </div>
    </motion.div>
  )
}

/* ── Main component ───────────────────────────────────────────── */
export function CommandCenter() {
  const { botStatus, runtimeOverride, setRuntimeOverride, setEmergencyStop, marketState } = useTradingStore()
  const pause      = useAction()
  const forceClose = useAction()
  const stop       = useAction()
  const kite       = useAction()
  const [showEntry, setShowEntry] = useState(false)

  const isPaused   = botStatus?.paused   ?? runtimeOverride.paused  ?? false
  const isHalted   = botStatus?.halt_active ?? false
  const hasPos     = botStatus?.state === 'ACTIVE' || botStatus?.position?.state === 'ACTIVE'
  const paperMode  = botStatus?.paper_mode ?? true
  const kiteOk     = botStatus?.kite_connected ?? false

  // Override values (fall back to live config)
  const maxTrades  = runtimeOverride.max_trades ?? botStatus?.max_trades ?? 3
  const lotsOvr    = runtimeOverride.lots ?? 0            // 0 = not set
  const vixMax     = runtimeOverride.vix_max ?? (botStatus as any)?.vix_max ?? 18
  const stratFilt  = runtimeOverride.strategy_filter ?? 'ALL'

  // Live VIX from market state
  const liveVix    = marketState?.regime_vix ?? (botStatus as any)?.regime_vix ?? null
  const vixBlocked = liveVix != null && liveVix > vixMax

  const patchOverride = async (patch: Record<string, unknown>) => {
    try {
      const r = await axios.post(`${API}/bot/override`, patch)
      setRuntimeOverride(r.data.overrides ?? r.data)
    } catch { /* silently fail — UI will show stale values */ }
  }

  const handlePause = () =>
    pause.run(
      isPaused ? () => axios.delete(`${API}/bot/pause`) : () => axios.post(`${API}/bot/pause`),
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
      'Force-close current position at market? This cannot be undone.'
    )

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/15 flex items-center justify-center">
            <Settings2 size={13} className="text-accent" />
          </div>
          <span className="text-[11px] font-bold uppercase tracking-widest text-text3">Bot Controls</span>
        </div>
        <div className={clsx(
          'text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded-md border',
          isHalted ? 'bg-red/15 border-red/30 text-red animate-pulse'
          : isPaused ? 'bg-amber/15 border-amber/30 text-amber'
          : 'bg-green/10 border-green/25 text-green'
        )}>
          {isHalted ? '⚡ HALTED' : isPaused ? '⏸ PAUSED' : '▶ LIVE'}
        </div>
      </div>

      {/* Primary controls */}
      <div className="grid grid-cols-2 gap-2">
        <Btn label={isPaused ? 'Resume' : 'Pause'} icon={isPaused ? Play : Pause}
          onClick={handlePause} variant={isPaused ? 'green' : 'amber'}
          disabled={isHalted || pause.loading} />
        <Btn label={isHalted ? 'Clear Halt' : 'E-STOP'} icon={isHalted ? Shield : AlertTriangle}
          onClick={handleStop} variant={isHalted ? 'green' : 'red'} disabled={stop.loading} />
      </div>

      {/* Force-close (only when position open) */}
      <AnimatePresence>
        {hasPos && (
          <motion.div initial={{ opacity:0, height:0 }} animate={{ opacity:1, height:'auto' }}
            exit={{ opacity:0, height:0 }} className="overflow-hidden">
            <Btn label={forceClose.ok ? '✓ Close sent' : 'Force Exit Position'}
              icon={LogOut} onClick={handleForceClose}
              variant={forceClose.ok ? 'green' : 'red'}
              disabled={forceClose.loading} fullWidth />
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── VIX Max Override ─────────────────────── */}
      <div className="border-t border-line/20 pt-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Gauge size={11} className={vixBlocked ? 'text-red' : 'text-amber'} />
            <span className="text-[11px] text-text3">VIX Max Override</span>
            {vixBlocked && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-red/10 text-red border border-red/20 font-bold animate-pulse">
                BLOCKED (live {liveVix?.toFixed(1)})
              </span>
            )}
          </div>
          <span className={clsx('font-mono font-bold text-[12px]',
            vixMax <= 18 ? 'text-green' : vixMax <= 22 ? 'text-cyan' : vixMax <= 25 ? 'text-amber' : 'text-red')}>
            {vixMax}
          </span>
        </div>
        {/* VIX preset chips */}
        <div className="flex gap-1">
          {VIX_PRESETS.map(p => (
            <button key={p.val} onClick={() => patchOverride({ vix_max: p.val })}
              className={clsx(
                'flex-1 py-1 rounded-lg border text-[9px] font-bold transition-all text-center',
                vixMax === p.val ? p.color : 'bg-surface border-line/30 text-text3 hover:border-accent/30'
              )}>
              {p.label}
              <span className="block text-[8px] font-mono opacity-70">{p.val}</span>
            </button>
          ))}
        </div>
        {/* Custom VIX stepper */}
        <Stepper label="Custom" value={vixMax} suffix=""
          onUp={() => patchOverride({ vix_max: vixMax + 1 })}
          onDown={() => patchOverride({ vix_max: Math.max(14, vixMax - 1) })}
          min={14} max={45} />
      </div>

      {/* ── Trade params ─────────────────────────── */}
      <div className="border-t border-line/20 pt-3 space-y-2">
        <Stepper label="Max Trades / Day" value={maxTrades}
          onUp={() => patchOverride({ max_trades: maxTrades + 1 })}
          onDown={() => patchOverride({ max_trades: Math.max(1, maxTrades - 1) })}
          min={1} max={10} />
        <Stepper label="Lots Override (0=auto)" value={lotsOvr}
          onUp={() => patchOverride({ lots: lotsOvr + 1 })}
          onDown={() => patchOverride({ lots: Math.max(0, lotsOvr - 1) })}
          min={0} max={10} />
      </div>

      {/* ── Strategy filter ──────────────────────── */}
      <div className="border-t border-line/20 pt-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Filter size={10} className="text-text3" />
          <span className="text-[11px] text-text3">Signal Filter</span>
        </div>
        <div className="flex gap-1">
          {(['ALL','CE','PE'] as const).map(f => (
            <button key={f} onClick={() => patchOverride({ strategy_filter: f })}
              className={clsx(
                'flex-1 py-1.5 rounded-lg border text-[10px] font-bold transition-all',
                stratFilt === f
                  ? f === 'CE' ? 'bg-green/15 border-green/30 text-green'
                  : f === 'PE' ? 'bg-red/15 border-red/30 text-red'
                  : 'bg-accent/15 border-accent/30 text-accent'
                  : 'bg-surface border-line/30 text-text3 hover:border-accent/30'
              )}>
              {f === 'CE' ? '↑ CE' : f === 'PE' ? '↓ PE' : 'All'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Paper mode + Kite ────────────────────── */}
      <div className="border-t border-line/20 pt-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text3">Paper Mode</span>
          <button onClick={() => patchOverride({ paper_mode: !paperMode })}
            className={clsx('flex items-center gap-1.5 text-[11px] font-bold transition-all',
              paperMode ? 'text-amber' : 'text-green')}>
            {paperMode ? <ToggleLeft size={16} /> : <ToggleRight size={16} />}
            {paperMode ? 'ON (safe)' : 'LIVE 🔥'}
          </button>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className={clsx('w-1.5 h-1.5 rounded-full', kiteOk ? 'bg-green animate-pulse' : 'bg-red')} />
            <span className="text-[11px] text-text3">{kiteOk ? 'Kite Connected' : 'Kite Offline'}</span>
          </div>
          <button onClick={() => kite.run(() => axios.get(`${API}/kite/verify`))}
            disabled={kite.loading}
            className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-lg border border-line/30 text-text3 hover:text-accent hover:border-accent/30 transition-all">
            <RefreshCw size={9} className={kite.loading ? 'animate-spin' : ''} />
            {kite.ok ? '✓ OK' : kite.err ? '✗ Fail' : 'Verify'}
          </button>
        </div>
      </div>

      {/* ── Manual entry panel ───────────────────── */}
      <div className="border-t border-line/20 pt-3">
        <button onClick={() => setShowEntry(s => !s)}
          className={clsx(
            'w-full flex items-center justify-center gap-2 py-2 rounded-xl border text-[11px] font-bold transition-all',
            showEntry
              ? 'bg-accent/15 border-accent/30 text-accent'
              : 'bg-surface border-line/30 text-text3 hover:border-accent/30 hover:text-accent'
          )}>
          <LogIn size={11} />
          {showEntry ? 'Hide Manual Entry' : 'Manual Entry Signal'}
        </button>
        <AnimatePresence>
          {showEntry && <ManualEntryPanel onClose={() => setShowEntry(false)} />}
        </AnimatePresence>
      </div>

      {/* Kite auth link */}
      {!kiteOk && (
        <a href="#" onClick={e => { e.preventDefault(); window.open('/api/kite/auth-url', '_blank') }}
          className="flex items-center justify-center gap-2 text-[10px] text-cyan font-bold py-1.5 px-3 rounded-xl border border-cyan/20 bg-cyan/5 hover:bg-cyan/10 transition-all">
          <Zap size={10} /> Login with Kite
        </a>
      )}
    </div>
  )
}