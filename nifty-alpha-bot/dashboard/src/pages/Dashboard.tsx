import React from 'react'
import { useTradingStore } from '../stores/tradingStore'
import { LivePnLPanel } from '../components/panels/LivePnLPanel'
import { FilterVisualizer } from '../components/panels/FilterVisualizer'
import { TradeLogTable } from '../components/panels/TradeLogTable'
import { Clock, Zap, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'

export function Dashboard() {
  const { position, trades, events } = useTradingStore()
  const isActive   = position.state === 'ACTIVE'
  const lastTrade  = trades[0]
  const today      = new Date().toISOString().slice(0, 10)
  const todayTrades = trades.filter(t => (t.trade_date ?? t.entry_ts?.slice(0,10)) === today)

  return (
    <div className="p-4 lg:p-5 space-y-4 max-w-screen-2xl mx-auto">
      {/* Metric strip */}
      <LivePnLPanel />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* ── Left column ── */}
        <div className="flex flex-col gap-4">
          {isActive ? <PositionCard position={position} /> : <IdleCard />}
          <EventFeed events={events} />
        </div>

        {/* ── Right column ── */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          {lastTrade?.filter_log && (
            <FilterVisualizer
              filters={lastTrade.filter_log}
              title={`Last Signal — ${lastTrade.strategy?.replace('_DAILY','') ?? ''} ${lastTrade.direction ?? ''}`}
            />
          )}

          <div className="bg-card rounded-xl border border-line flex-1">
            <div className="flex items-center justify-between px-4 py-3 border-b border-line">
              <span className="text-sm font-semibold text-text1">Today's Trades</span>
              <span className="text-[11px] font-semibold tracking-widest uppercase text-text3">
                {todayTrades.length} trades
              </span>
            </div>
            <div className="p-2">
              <TradeLogTable trades={todayTrades} maxRows={10} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ────── Active Position Card ────── */
function PositionCard({ position }: { position: any }) {
  const isCall = position.direction === 'CALL'
  const gainPct = position.entry_price && position.highest_price_seen
    ? ((position.highest_price_seen - position.entry_price) / position.entry_price) * 100
    : 0
  const estPnl = position.entry_price && position.highest_price_seen
    ? (position.highest_price_seen - position.entry_price) * (position.lots ?? 1) * 65
    : 0

  return (
    <div className={clsx(
      'rounded-xl border p-5',
      isCall
        ? 'bg-greenDim/40 border-green/25'
        : 'bg-redDim/40 border-red/25'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-60"/>
            <span className="relative rounded-full h-2.5 w-2.5 bg-green"/>
          </span>
          <span className="text-xs font-bold uppercase tracking-widest text-text2">Open Position</span>
        </div>
        <span className="text-[11px] font-bold px-2.5 py-1 rounded-lg bg-accentDim border border-accent/25 text-accent">
          {position.strategy}
        </span>
      </div>

      {/* Direction & P&L */}
      <div className="flex items-end justify-between mb-5">
        <div>
          <div className={clsx(
            'text-4xl font-black tracking-tight font-mono',
            isCall ? 'text-green' : 'text-red'
          )}>
            {position.direction}
          </div>
          <div className="text-xs text-text3 font-mono mt-1">{position.symbol ?? '--'} · {position.option_type}</div>
        </div>
        <div className="text-right">
          <div className={clsx('text-2xl font-bold font-mono', gainPct >= 0 ? 'text-green' : 'text-red')}>
            {gainPct >= 0 ? '+' : ''}{gainPct.toFixed(1)}%
          </div>
          <div className={clsx('text-sm font-mono font-semibold', gainPct >= 0 ? 'text-green' : 'text-red')}>
            {gainPct >= 0 ? '+' : ''}₹{Math.abs(estPnl).toLocaleString('en-IN',{maximumFractionDigits:0})}
          </div>
          <div className="text-[10px] text-text3 mt-0.5">est. unrealised</div>
        </div>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        {([
          { label:'Entry',   val: position.entry_price,  cls:'text-text1' },
          { label:'Stop',    val: position.current_sl,   cls:'text-red' },
          { label:'Target',  val: position.target_price, cls:'text-green' },
        ] as {label:string;val?:number;cls:string}[]).map(({ label, val, cls }) => (
          <div key={label} className="bg-bg/60 rounded-lg p-2.5 text-center">
            <div className="text-[10px] font-semibold tracking-widest uppercase text-text3 mb-1">{label}</div>
            <div className={clsx('font-mono text-sm font-bold', cls)}>
              {val != null ? `₹${val.toFixed(0)}` : '--'}
            </div>
          </div>
        ))}
      </div>

      {position.break_even_set && (
        <div className="flex items-center gap-2 bg-accentDim rounded-lg border border-accent/20 px-3 py-2">
          <ShieldCheck size={13} className="text-accent shrink-0" />
          <span className="text-xs font-semibold text-accent">Break-even protection active</span>
        </div>
      )}
    </div>
  )
}

/* ────── Idle / Waiting Card ────── */
function IdleCard() {
  const now  = new Date()
  const h    = now.getHours()
  const min  = now.getMinutes()
  const open = (h > 9 || (h === 9 && min >= 15)) && h < 15
  const time = now.toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', hour12:true })

  return (
    <div className="bg-card rounded-xl border border-line p-5">
      <div className="flex items-center gap-2 mb-4">
        <Clock size={14} className="text-text3" />
        <span className="text-sm font-semibold text-text1">No Open Position</span>
      </div>

      <div className="flex flex-col items-center py-4 gap-3">
        <div className={clsx(
          'flex items-center gap-2 px-4 py-2 rounded-full border text-sm font-semibold',
          open
            ? 'bg-greenDim border-green/30 text-green'
            : 'bg-bg border-line text-text3'
        )}>
          {open && (
            <span className="relative flex h-2 w-2 shrink-0">
              <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-60"/>
              <span className="relative h-2 w-2 rounded-full bg-green"/>
            </span>
          )}
          {open ? 'Market Open' : 'Market Closed'}
        </div>

        <p className="text-sm text-text2 text-center font-medium">
          {open ? 'Scanning for ORB & VWAP signals...' : 'Bot resumes at 9:15 AM IST'}
        </p>

        <div className="flex flex-col items-center gap-1 mt-1">
          <span className="font-mono text-sm text-text2 font-semibold">{time} IST</span>
          <span className="text-xs text-text3">Market: 9:15 AM – 3:30 PM</span>
        </div>
      </div>
    </div>
  )
}

/* ────── Event Feed ────── */
const EV_DOT: Record<string, string> = {
  ENTRY:        'bg-green',
  TRADE_CLOSED: 'bg-accent',
  ORB_SCAN:     'bg-text3',
  RECLAIM_SCAN: 'bg-text3',
  LOOP_ERROR:   'bg-red',
  auth_check:   'bg-amber',
}

function EventFeed({ events }: { events: any[] }) {
  return (
    <div className="bg-card rounded-xl border border-line">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line">
        <div className="flex items-center gap-2">
          <Zap size={13} className="text-accent" />
          <span className="text-sm font-semibold text-text1">Event Feed</span>
        </div>
        {events.length > 0 && (
          <span className="text-[11px] font-semibold tracking-widest uppercase text-text3">{events.length}</span>
        )}
      </div>

      <div className="divide-y divide-line/40 max-h-56 overflow-y-auto">
        {events.slice(0, 20).map((e, i) => (
          <div key={i} className="flex items-start gap-3 px-4 py-2.5">
            <div className={clsx('w-1.5 h-1.5 rounded-full mt-1.5 shrink-0', EV_DOT[e.event] ?? 'bg-text3')} />
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-semibold text-text2">{e.event}</span>
                {e.signal && (
                  <span className={clsx('text-xs font-bold', e.signal === 'CALL' ? 'text-green' : 'text-red')}>
                    {e.signal}
                  </span>
                )}
                <span className="font-mono text-[10px] text-text3 ml-auto shrink-0">
                  {e.ts?.slice(11, 19)}
                </span>
              </div>
              {e.message && (
                <p className="text-[10px] text-text3 truncate mt-0.5">{e.message}</p>
              )}
            </div>
          </div>
        ))}
        {!events.length && (
          <div className="px-4 py-6 text-center text-xs text-text3">
            No events yet — bot activity appears here in real-time
          </div>
        )}
      </div>
    </div>
  )
}
