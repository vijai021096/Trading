import React, { useState } from 'react'
import { useTradingStore } from '../stores/tradingStore'
import { TradeLogTable } from '../components/panels/TradeLogTable'
import clsx from 'clsx'

type Filter = 'all' | 'win' | 'loss' | 'ORB' | 'VWAP_RECLAIM'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all',          label: 'All' },
  { id: 'win',          label: 'Winners' },
  { id: 'loss',         label: 'Losers' },
  { id: 'ORB',          label: 'ORB' },
  { id: 'VWAP_RECLAIM', label: 'VWAP Reclaim' },
]

export function TradeHistory() {
  const { trades } = useTradingStore()
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = trades.filter(t => {
    if (filter === 'win')          return (t.net_pnl ?? 0) > 0
    if (filter === 'loss')         return (t.net_pnl ?? 0) <= 0
    if (filter === 'ORB')          return (t.strategy ?? '').includes('ORB')
    if (filter === 'VWAP_RECLAIM') return t.strategy === 'VWAP_RECLAIM'
    return true
  })

  const totalPnl     = filtered.reduce((s, t) => s + (t.net_pnl ?? 0), 0)
  const totalCharges = filtered.reduce((s, t) => s + (t.charges ?? 0), 0)
  const wins         = filtered.filter(t => (t.net_pnl ?? 0) > 0).length
  const losses       = filtered.length - wins
  const winRate      = filtered.length > 0 ? (wins / filtered.length) * 100 : 0

  return (
    <div className="p-4 lg:p-5 space-y-4 max-w-screen-2xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-text1 tracking-tight">Trade History</h1>
        <span className="font-mono text-xs text-text3">{trades.length} total trades</span>
      </div>

      {/* Summary row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {([
          { label: 'Net P&L',   value: `${totalPnl >= 0 ? '+' : ''}₹${Math.abs(totalPnl).toLocaleString('en-IN', {maximumFractionDigits:0})}`, color: totalPnl >= 0 ? 'text-green' : 'text-red' },
          { label: 'Win Rate',  value: `${winRate.toFixed(1)}%`,  sub: `${wins}W · ${losses}L`, color: winRate >= 50 ? 'text-green' : 'text-red' },
          { label: 'Trades',    value: String(filtered.length),   color: 'text-text1' },
          { label: 'Charges',   value: `₹${totalCharges.toLocaleString('en-IN', {maximumFractionDigits:0})}`, color: 'text-text2' },
        ] as { label:string; value:string; sub?:string; color:string }[]).map(({ label, value, sub, color }) => (
          <div key={label} className="bg-card rounded-xl border border-line p-4">
            <div className="text-[11px] font-semibold tracking-widest uppercase text-text3 mb-2">{label}</div>
            <div className={clsx('text-xl font-bold font-mono', color)}>{value}</div>
            {sub && <div className="text-xs text-text3 mt-1">{sub}</div>}
          </div>
        ))}
      </div>

      {/* Filter pills */}
      <div className="flex gap-2 flex-wrap">
        {FILTERS.map(f => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={clsx(
              'px-4 py-1.5 rounded-lg text-xs font-semibold border transition-all',
              filter === f.id
                ? 'bg-accent border-accent text-white'
                : 'bg-card border-line text-text3 hover:text-text2 hover:border-lineHi'
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-card rounded-xl border border-line">
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <span className="text-sm font-semibold text-text1">
            {FILTERS.find(f => f.id === filter)?.label ?? 'All Trades'}
          </span>
          <span className="text-[11px] font-semibold tracking-widest uppercase text-text3">{filtered.length} results</span>
        </div>
        <div className="p-2">
          <TradeLogTable trades={filtered} />
        </div>
      </div>
    </div>
  )
}
