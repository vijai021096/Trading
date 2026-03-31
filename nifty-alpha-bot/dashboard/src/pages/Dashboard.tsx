/**
 * Dashboard — main live trading terminal view.
 * Composes modular panel components; stays lean and readable.
 */
import { useMemo } from 'react'
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { Activity, Radio, Cpu, Clock4 } from 'lucide-react'
import { useTradingStore } from '../stores/tradingStore'
import { CommandCenter }   from '../components/panels/CommandCenter'
import { PositionMonitor } from '../components/panels/PositionMonitor'
import { PnlHero }         from '../components/panels/PnlHero'
import { MarketIntel }     from '../components/panels/MarketIntel'
import { RiskPanel }       from '../components/panels/RiskPanel'
import { EventFeed }       from '../components/panels/EventFeed'

/* ── Tiny helper components (only used in this file) ─────────── */

function StatusPill({ label, color, pulse = false }: { label: string; color: string; pulse?: boolean }) {
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest px-2.5 py-1 rounded-lg border',
      color,
      pulse && 'animate-pulse'
    )}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
    </span>
  )
}

function ThinkingBar({ thinking }: { thinking: string }) {
  if (!thinking) return null
  return (
    <motion.div
      key={thinking}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-2 px-4 py-2 rounded-xl bg-accent/5 border border-accent/15"
    >
      <Cpu size={12} className="text-accent-l shrink-0 animate-pulse" />
      <p className="text-xs text-text3 font-medium leading-relaxed">{thinking}</p>
    </motion.div>
  )
}

function MarketStatusBar() {
  const { botStatus, connected, lastUpdate } = useTradingStore()

  const marketStatus = botStatus?.market_status ?? 'UNKNOWN'
  const paperMode    = botStatus?.paper_mode ?? true
  const engine       = botStatus?.trading_engine ?? '—'
  const kiteOk = botStatus?.kite_connected ?? false

  const statusColor = {
    OPEN:       'bg-green/10 border-green/25 text-green',
    CLOSED:     'bg-surface border-line/30 text-text3',
    PRE_MARKET: 'bg-amber/10 border-amber/25 text-amber',
    POST_MARKET:'bg-surface border-line/30 text-text3',
    WEEKEND:    'bg-surface border-line/30 text-text3',
    UNKNOWN:    'bg-surface border-line/30 text-text3',
  }[marketStatus] ?? 'bg-surface border-line/30 text-text3'

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <StatusPill
        label={marketStatus.replace('_', ' ')}
        color={statusColor}
        pulse={marketStatus === 'OPEN'}
      />
      {paperMode && (
        <StatusPill label="Paper" color="bg-amber/10 border-amber/25 text-amber" />
      )}
      <StatusPill
        label={kiteOk ? 'Kite ✓' : 'Kite ✗'}
        color={kiteOk ? 'bg-green/10 border-green/25 text-green' : 'bg-red/10 border-red/25 text-red'}
      />
      <StatusPill
        label={engine.replace('_', ' ')}
        color="bg-accent/10 border-accent/25 text-accent-l"
      />
      {lastUpdate && (
        <span className="flex items-center gap-1 text-[10px] text-text3 font-mono">
          <Clock4 size={9} />{lastUpdate}
        </span>
      )}
      {!connected && (
        <StatusPill label="Disconnected" color="bg-red/10 border-red/25 text-red" pulse />
      )}
    </div>
  )
}

interface ScanLeg {
  strategy: string; signal: string | null; passed: boolean; confidence: number
  regime?: string; lots?: number; sl_pct?: number; target_pct?: number
}
interface ScanSummary {
  strategies_evaluated: number; signals_detected: number; vix?: number
  candidates: Array<{ strategy: string; signal: string; confidence: number }>
  scans: ScanLeg[]
}

function ScanLegTable({ scan }: { scan: ScanSummary | null }) {
  if (!scan?.scans?.length) return null
  return (
    <div className="glass-card rounded-2xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
          <Radio size={12} className="text-accent-l" />
        </div>
        <span className="text-xs font-bold uppercase tracking-widest text-text3">Signal Legs</span>
        {scan.vix && (
          <span className="ml-auto text-[10px] font-mono text-amber">VIX {Number(scan.vix).toFixed(1)}</span>
        )}
      </div>
      <div className="space-y-1.5">
        {scan.scans.map((s: ScanLeg, i: number) => (
          <div key={i} className={clsx(
            'flex items-center gap-3 py-2 px-3 rounded-xl text-xs',
            s.passed ? 'bg-green/8 border border-green/15' : 'bg-surface/50 border border-line/20'
          )}>
            <span className={clsx('font-black', s.signal === 'BUY' ? 'text-green' : s.signal === 'SELL' ? 'text-red' : 'text-text3')}>
              {s.signal ?? '—'}
            </span>
            <span className="flex-1 font-medium text-text2">{s.strategy}</span>
            {s.lots != null && <span className="text-text3">{s.lots}L</span>}
            {s.sl_pct != null && <span className="text-red-l font-mono">SL {(s.sl_pct * 100).toFixed(1)}%</span>}
            {s.target_pct != null && <span className="text-green-l font-mono">T {(s.target_pct * 100).toFixed(1)}%</span>}
            {s.confidence > 0 && (
              <span className="text-text3 font-mono">{s.confidence.toFixed(0)}%</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Main Dashboard ──────────────────────────────────────────── */

const fadeUp = {
  initial:    { opacity: 0, y: 12 },
  animate:    { opacity: 1, y: 0 },
  transition: { duration: 0.35, ease: 'easeOut' as const },
}

export function Dashboard() {
  const { botStatus } = useTradingStore()

  const thinking = botStatus?.thinking ?? ''
  const scan     = (botStatus?.last_scan ?? null) as ScanSummary | null

  // Detect bot state
  const state = botStatus?.state ?? 'IDLE'
  const stateColor =
    state === 'ACTIVE'  ? 'bg-green/10 border-green/25 text-green'
    : state === 'IDLE'  ? 'bg-surface border-line/30 text-text3'
    : 'bg-amber/10 border-amber/25 text-amber'

  return (
    <div className="p-4 lg:p-6 max-w-[1640px] mx-auto space-y-4">
      {/* ── Row 0: Status bar ── */}
      <motion.div {...fadeUp}
        className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-black uppercase tracking-widest', stateColor)}>
            <Activity size={12} className={state === 'ACTIVE' ? 'animate-pulse' : ''} />
            {state}
          </div>
          <MarketStatusBar />
        </div>
      </motion.div>

      {/* ── Thinking bar ── */}
      {thinking && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
          <ThinkingBar thinking={thinking} />
        </motion.div>
      )}

      {/* ── Row 1: Three top panels ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <CommandCenter />
        <PnlHero />
        <PositionMonitor />
      </div>

      {/* ── Row 2: Intelligence + Risk ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <MarketIntel />
        <RiskPanel />
      </div>

      {/* ── Row 3: Signal legs (if any) ── */}
      {scan?.scans && scan.scans.length > 0 && (
        <ScanLegTable scan={scan} />
      )}

      {/* ── Row 4: Event feed ── */}
      <EventFeed maxRows={30} />
    </div>
  )
}