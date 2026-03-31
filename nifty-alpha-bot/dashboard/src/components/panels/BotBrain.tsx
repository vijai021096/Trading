/**
 * BotBrain — surfaces ALL bot intelligence:
 *   narrative • thinking • what it's waiting for
 *   entry window countdown • trade plan summary
 *   last trade context • scan stats
 */
import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import {
  Brain, Clock, Target, Zap, CheckCircle2, AlertCircle,
  TrendingUp, TrendingDown, Activity, Minus, Hourglass,
} from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

function parseWindow(thinking: string): { inWindow: boolean; start: string; end: string } {
  const m = thinking?.match(/(\d{2}:\d{2})\u2013(\d{2}:\d{2})/)
  if (!m) return { inWindow: false, start: '09:16', end: '13:00' }
  return { inWindow: true, start: m[1], end: m[2] }
}

function WindowClock({ thinking }: { thinking?: string }) {
  const win = useMemo(() => parseWindow(thinking ?? ''), [thinking])
  const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
  const afterStart = now >= (win.start || '09:16')
  const beforeEnd  = now <= (win.end   || '13:00')
  const active     = afterStart && beforeEnd

  const [startH, startM] = (win.start || '09:16').split(':').map(Number)
  const [endH,   endM  ] = (win.end   || '13:00').split(':').map(Number)
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes()
  const startMin = startH * 60 + startM
  const endMin   = endH   * 60 + endM
  const pct = active
    ? Math.min(100, ((nowMin - startMin) / (endMin - startMin)) * 100)
    : nowMin < startMin ? 0 : 100

  const remMin = active ? endMin - nowMin : afterStart ? 0 : startMin - nowMin
  const remStr = remMin > 0 ? `${Math.floor(remMin / 60)}h ${remMin % 60}m left` : active ? 'closing soon' : 'window closed'

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <Clock size={11} className={active ? 'text-accent' : 'text-text3'} />
          <span className="label">Entry Window</span>
          <span className={clsx(
            'text-[9px] font-black px-1.5 py-0.5 rounded border',
            active ? 'text-accent bg-accent/10 border-accent/25' : 'text-text3 bg-surface border-line/30'
          )}>
            {active ? 'OPEN' : nowMin < startMin ? 'PRE' : 'CLOSED'}
          </span>
        </div>
        <span className="font-mono text-[10px] text-text2">{win.start}–{win.end} IST</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface overflow-hidden">
        <motion.div className={clsx('h-full rounded-full', active ? 'bg-accent' : 'bg-text3/30')}
          initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.8 }} />
      </div>
      <div className={clsx('text-[10px] mt-1', active ? 'text-accent/80' : 'text-text3')}>{remStr}</div>
    </div>
  )
}

function WaitingFor({ thinking, state }: { thinking?: string; state?: string }) {
  const items: { label: string; ok: boolean }[] = []

  if (thinking) {
    const t = thinking.toLowerCase()
    items.push({ label: 'Entry window open',      ok: /\d{2}:\d{2}/.test(thinking) && !t.includes('waiting for open') })
    items.push({ label: 'Bot idle (no position)', ok: state === 'IDLE' })
    items.push({ label: 'Trade cap not reached',  ok: !t.includes('cap reached') && !t.includes('0 remaining') })
    items.push({ label: 'Daily loss OK',           ok: !t.includes('halt') && !t.includes('limit hit') })
    items.push({ label: 'VIX acceptable',          ok: !t.includes('vix too high') && !t.includes('vix skip') })
    items.push({ label: 'Signal quality A+',       ok: t.includes('a+') || t.includes('quality') })
  }

  if (!items.length) return null
  const allGood = items.every(i => i.ok)

  return (
    <div className="mb-4 p-3 rounded-xl bg-surface/50 border border-line/30">
      <div className="flex items-center gap-1.5 mb-2">
        <Hourglass size={10} className={allGood ? 'text-green' : 'text-amber'} />
        <span className="label">{allGood ? 'All conditions met — waiting for signal' : 'Waiting for'}</span>
      </div>
      <div className="grid grid-cols-2 gap-1">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-1.5 text-[10px]">
            {item.ok
              ? <CheckCircle2 size={10} className="text-green shrink-0" />
              : <AlertCircle  size={10} className="text-amber shrink-0" />}
            <span className={item.ok ? 'text-text2' : 'text-amber/90'}>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LastTrade({ botStatus }: { botStatus: any }) {
  const last = botStatus?.last_exit_reason ?? botStatus?.last_trade_pnl != null ? botStatus : null
  if (!last?.last_trade_pnl && !last?.last_exit_reason) return null
  const pnl = last.last_trade_pnl ?? 0
  const win = pnl > 0
  return (
    <div className={clsx(
      'mb-4 p-3 rounded-xl border text-[11px]',
      win ? 'bg-green/5 border-green/15' : 'bg-red/5 border-red/15'
    )}>
      <div className="label mb-1">Last Trade</div>
      <div className="flex items-center justify-between">
        <span className="text-text2">{last.last_exit_reason ?? (win ? 'Target hit' : 'Stop loss hit')}</span>
        <span className={clsx('font-mono font-bold', win ? 'text-green' : 'text-red-l')}>
          {win ? '+' : ''}₹{Math.abs(pnl).toFixed(0)}
        </span>
      </div>
    </div>
  )
}

export function BotBrain() {
  const { botStatus } = useTradingStore()

  const thinking  = botStatus?.thinking ?? ''
  const state     = botStatus?.state ?? 'IDLE'
  const trades    = botStatus?.trades_today ?? 0
  const maxTrades = botStatus?.max_trades ?? 3
  const engine    = botStatus?.trading_engine ?? botStatus?.strategies?.active_engine ?? null
  const regime    = botStatus?.daily_regime ?? botStatus?.regime ?? null
  const filter    = botStatus?.daily_strategy_filter ?? null
  const scanCount = botStatus?.scan_count_today ?? null
  const skipped   = botStatus?.skipped_today ?? null

  // Parse the narrative (split on — or . to get meaningful phrases)
  const narrative = useMemo(() => {
    if (!thinking) return []
    return thinking
      .split(/\s*[—·|]\s*/)
      .map(s => s.trim())
      .filter(Boolean)
      .slice(0, 4)
  }, [thinking])

  return (
    <div className="glass-card rounded-2xl p-5 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <Brain size={14} className="text-accent" />
          </div>
          <span className="label">Bot Brain</span>
        </div>
        <div className="flex items-center gap-1.5">
          {state === 'ACTIVE' && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-60" />
              <span className="relative rounded-full h-2 w-2 bg-green" />
            </span>
          )}
          <span className={clsx(
            'text-[10px] font-black px-2 py-0.5 rounded border',
            state === 'ACTIVE'
              ? 'bg-green/10 text-green border-green/25'
              : 'bg-surface text-text3 border-line/30'
          )}>{state}</span>
          <span className="text-[10px] font-mono text-text3">{trades}/{maxTrades}</span>
        </div>
      </div>

      {/* Regime + engine row */}
      {(regime || engine || filter) && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {regime && (
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-cyan/10 text-cyan border border-cyan/20 font-bold">
              {regime}
            </span>
          )}
          {engine && (
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-accent/10 text-accent border border-accent/20 font-bold">
              {engine.replace(/_/g, ' ')}
            </span>
          )}
          {filter && filter !== 'BOTH' && (
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-surface text-text2 border border-line/30 font-bold">
              filter: {filter}
            </span>
          )}
          {scanCount != null && (
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-surface text-text3 border border-line/30">
              {scanCount} scans
            </span>
          )}
          {skipped != null && skipped > 0 && (
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-amber/10 text-amber border border-amber/20">
              {skipped} skipped
            </span>
          )}
        </div>
      )}

      {/* Narrative chips */}
      {narrative.length > 0 && (
        <AnimatePresence mode="popLayout">
          <div className="mb-3 space-y-1">
            {narrative.map((line, i) => (
              <motion.div key={line}
                initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04 }}
                className="flex items-start gap-2 text-[11px] leading-relaxed">
                <span className="mt-1.5 w-1 h-1 rounded-full bg-accent/60 shrink-0" />
                <span className={i === 0 ? 'text-text1 font-medium' : 'text-text2'}>{line}</span>
              </motion.div>
            ))}
          </div>
        </AnimatePresence>
      )}

      {!thinking && (
        <div className="text-[11px] text-text3 italic mb-3">Waiting for heartbeat...</div>
      )}

      {/* Entry window progress */}
      <WindowClock thinking={thinking} />

      {/* What it's waiting for */}
      <WaitingFor thinking={thinking} state={state} />

      {/* Last trade */}
      <LastTrade botStatus={botStatus} />

      {/* Scan stats row */}
      <div className="mt-auto pt-3 border-t border-line/20 flex items-center gap-4 text-[10px]">
        <div className="flex items-center gap-1.5">
          <Activity size={10} className="text-accent" />
          <span className="text-text3">Trades today:</span>
          <span className="font-mono font-bold text-text1">{trades}/{maxTrades}</span>
        </div>
        {botStatus?.lots_planning != null && (
          <div className="flex items-center gap-1.5">
            <Target size={10} className="text-cyan" />
            <span className="text-text3">Planning:</span>
            <span className="font-mono font-bold text-cyan">{botStatus.lots_planning} lot{botStatus.lots_planning !== 1 ? 's' : ''}</span>
          </div>
        )}
      </div>
    </div>
  )
}