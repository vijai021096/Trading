/**
 * EventFeed — live scrolling bot event stream with color-coded event types.
 */
import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import { Zap, TrendingUp, TrendingDown, AlertTriangle, Info, CheckCircle, XCircle, Wifi } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

const EVENT_META: Record<string, { icon: typeof Zap; color: string; bg: string }> = {
  ENTRY:                 { icon: TrendingUp,    color: 'text-green',   bg: 'bg-green/8' },
  EXIT:                  { icon: TrendingDown,  color: 'text-amber',   bg: 'bg-amber/8' },
  TRADE_CLOSED:          { icon: CheckCircle,   color: 'text-cyan',    bg: 'bg-cyan/8' },
  EMERGENCY_STOP:        { icon: AlertTriangle, color: 'text-red',     bg: 'bg-red/10' },
  BOT_PAUSED:            { icon: AlertTriangle, color: 'text-amber',   bg: 'bg-amber/8' },
  BOT_RESUMED:           { icon: CheckCircle,   color: 'text-green',   bg: 'bg-green/8' },
  FORCE_CLOSE_REQUESTED: { icon: XCircle,       color: 'text-red',     bg: 'bg-red/8' },
  KITE_AUTH:             { icon: Wifi,          color: 'text-cyan',    bg: 'bg-cyan/8' },
  DAILY_ADAPTIVE_SCAN:   { icon: Zap,           color: 'text-accent-l',bg: 'bg-accent/8' },
  DAILY_REGIME:          { icon: Info,          color: 'text-text2',   bg: 'bg-surface' },
  TREND_DETECTED:        { icon: TrendingUp,    color: 'text-cyan',    bg: 'bg-cyan/5' },
  TREND_SHIFTED:         { icon: TrendingUp,    color: 'text-cyan',    bg: 'bg-cyan/5' },
  REGIME_DETECTED:       { icon: Info,          color: 'text-accent-l',bg: 'bg-accent/5' },
  RUNTIME_OVERRIDE:      { icon: Zap,           color: 'text-amber',   bg: 'bg-amber/5' },
  HEARTBEAT:             { icon: Info,          color: 'text-text3',   bg: 'bg-surface/50' },
  SCAN_CYCLE:            { icon: Zap,           color: 'text-text3',   bg: 'bg-surface/50' },
}

const DEFAULT_META = { icon: Info, color: 'text-text3', bg: 'bg-surface/50' }

function fmtTime(ts: string): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return ts.slice(11, 19) || ts.slice(0, 8)
  }
}

function fmtPnl(ev: Record<string, unknown>): string | null {
  const pnl = ev.net_pnl ?? ev.pnl ?? ev.daily_pnl
  if (pnl == null) return null
  const n = Number(pnl)
  return `${n >= 0 ? '+' : ''}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function eventSummary(ev: Record<string, unknown>): string {
  const type = String(ev.event ?? '')
  if (type === 'ENTRY') {
    return `${ev.symbol ?? ''} ${ev.direction ?? ''} @ ₹${ev.entry_price ?? ''} (${ev.strategy ?? ''})`
  }
  if (type === 'TRADE_CLOSED' || type === 'EXIT') {
    const pnl = fmtPnl(ev)
    return `${ev.symbol ?? ev.strategy ?? ''} ${ev.exit_reason ?? 'CLOSED'} ${pnl ?? ''}`
  }
  if (type === 'DAILY_ADAPTIVE_SCAN') {
    return `Regime ${ev.regime ?? ''} · ${ev.vix ? `VIX ${ev.vix}` : ''}`
  }
  if (type === 'TREND_DETECTED' || type === 'TREND_SHIFTED') {
    return `${ev.state ?? ''} ${ev.direction ?? ''} · conviction ${ev.conviction ?? ''}%`
  }
  if (type === 'REGIME_DETECTED') {
    return `${ev.regime ?? ''} · ADX ${ev.adx_proxy ?? '—'} VIX ${ev.vix ?? '—'}`
  }
  if (type === 'HEARTBEAT') {
    return String(ev.thinking ?? 'Heartbeat')
  }
  if (type === 'KITE_AUTH') {
    return String(ev.message ?? 'Auth event')
  }
  if (type === 'RUNTIME_OVERRIDE') {
    return String(ev.message ?? 'Override changed')
  }
  if (ev.message) return String(ev.message)
  if (ev.thinking) return String(ev.thinking)
  return type
}

const HIDE_SPAM = new Set(['HEARTBEAT', 'SCAN_CYCLE'])

export function EventFeed({ showAll = false, maxRows = 25 }: { showAll?: boolean; maxRows?: number }) {
  const { events } = useTradingStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  const filtered = showAll
    ? events
    : events.filter(e => !HIDE_SPAM.has(e.event ?? ''))

  const visible = filtered.slice(0, maxRows)

  // Auto-scroll to top (newest events) on update
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [events.length])

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <Zap size={13} className="text-accent-l" />
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Live Events</span>
        </div>
        <span className="text-[10px] text-text3">{filtered.length} recent</span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-1 max-h-[340px] pr-1"
        style={{ scrollbarWidth: 'thin', scrollbarColor: '#2a3460 transparent' }}>
        <AnimatePresence initial={false}>
          {visible.map((ev, i) => {
            const type = String(ev.event ?? 'UNKNOWN')
            const meta = EVENT_META[type] ?? DEFAULT_META
            const Icon = meta.icon
            const pnl  = fmtPnl(ev)

            return (
              <motion.div
                key={`${ev.ts ?? i}-${i}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.2 }}
                className={clsx(
                  'flex items-start gap-2.5 py-2 px-2.5 rounded-xl border border-transparent transition-colors hover:border-line/20',
                  meta.bg
                )}
              >
                <Icon size={12} className={clsx('mt-0.5 shrink-0', meta.color)} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={clsx('text-[10px] font-black uppercase tracking-wide', meta.color)}>
                      {type.replace(/_/g, ' ')}
                    </span>
                    {pnl && (
                      <span className={clsx('text-[10px] font-bold font-mono', Number(pnl.replace(/[^\d.-]/g, '')) >= 0 ? 'text-green' : 'text-red')}>
                        {pnl}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-text3 truncate leading-tight mt-0.5">
                    {eventSummary(ev)}
                  </p>
                </div>
                <span className="text-[10px] font-mono text-text3/60 shrink-0">
                  {fmtTime(ev.ts ?? '')}
                </span>
              </motion.div>
            )
          })}
        </AnimatePresence>

        {visible.length === 0 && (
          <div className="text-center py-8 text-text3 text-xs">No events yet…</div>
        )}
      </div>
    </div>
  )
}