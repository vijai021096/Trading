import React, { useState } from 'react'
import clsx from 'clsx'
import { ChevronDown, ChevronRight, TrendingUp, TrendingDown } from 'lucide-react'
import { Trade } from '../../stores/tradingStore'
import { FilterVisualizer } from './FilterVisualizer'

export function TradeLogTable({ trades, maxRows }: { trades: Trade[]; maxRows?: number }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const rows = maxRows ? trades.slice(0, maxRows) : trades

  if (!rows.length) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-text3">
        <svg width="36" height="28" viewBox="0 0 36 28" fill="none" className="mb-3 opacity-40">
          <rect x="1" y="16" width="6" height="10" rx="1.5" fill="currentColor" />
          <rect x="10" y="9" width="6" height="17" rx="1.5" fill="currentColor" />
          <rect x="19" y="12" width="6" height="14" rx="1.5" fill="currentColor" />
          <rect x="28" y="3" width="6" height="23" rx="1.5" fill="currentColor" />
        </svg>
        <p className="text-sm font-medium text-text2">No trades yet</p>
        <p className="text-xs mt-1">Trades appear here during market hours</p>
      </div>
    )
  }

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-line">
            <th className="w-8 py-2.5 px-3" />
            {['Date','Direction','Strategy','Entry','Exit','SL','Target','Reason','P&L'].map(h => (
              <th key={h} className="py-2.5 px-3 text-left text-[11px] font-semibold tracking-wider uppercase text-text3 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((t, i) => {
            const id  = `${t.entry_ts}-${i}`
            const open = expanded === id
            const pos  = (t.net_pnl ?? 0) >= 0

            return (
              <React.Fragment key={id}>
                <tr
                  onClick={() => setExpanded(open ? null : id)}
                  className={clsx(
                    'border-b border-line/50 cursor-pointer transition-colors group',
                    open ? 'bg-cardHigh' : 'hover:bg-card/60'
                  )}
                >
                  <td className="py-3 px-3 text-text3 group-hover:text-text2">
                    {open ? <ChevronDown size={13}/> : <ChevronRight size={13}/>}
                  </td>

                  <td className="py-3 px-3 font-mono text-xs text-text2 whitespace-nowrap">
                    {t.trade_date ?? t.entry_ts?.slice(0,10) ?? '--'}
                  </td>

                  <td className="py-3 px-3">
                    <span className={clsx(
                      'inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded border',
                      t.direction === 'CALL'
                        ? 'bg-greenDim border-green/25 text-green'
                        : 'bg-redDim border-red/25 text-red'
                    )}>
                      {t.direction === 'CALL'
                        ? <TrendingUp size={10}/>
                        : <TrendingDown size={10}/>}
                      {t.direction} {t.option_type}
                    </span>
                  </td>

                  <td className="py-3 px-3">
                    <span className={clsx(
                      'text-[11px] font-bold px-2 py-0.5 rounded border',
                      (t.strategy ?? '').includes('ORB')
                        ? 'bg-accentDim border-accent/25 text-accent'
                        : 'bg-amberDim border-amber/25 text-amber'
                    )}>
                      {t.strategy?.replace('_DAILY','').replace('VWAP_RECLAIM','VWAP') ?? '--'}
                    </span>
                  </td>

                  <td className="py-3 px-3 font-mono text-sm text-text1 font-medium">₹{t.entry_price?.toFixed(0) ?? '--'}</td>
                  <td className="py-3 px-3 font-mono text-sm text-text2">{t.exit_price ? `₹${t.exit_price.toFixed(0)}` : '--'}</td>
                  <td className="py-3 px-3 font-mono text-sm text-red/80">₹{t.sl_price?.toFixed(0) ?? '--'}</td>
                  <td className="py-3 px-3 font-mono text-sm text-green/80">₹{t.target_price?.toFixed(0) ?? '--'}</td>

                  <td className="py-3 px-3">
                    <ExitBadge reason={t.exit_reason} />
                  </td>

                  <td className={clsx('py-3 px-3 font-mono text-sm font-bold whitespace-nowrap', pos ? 'text-green' : 'text-red')}>
                    {pos ? '+' : ''}₹{Math.abs(t.net_pnl ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </td>
                </tr>

                {open && (
                  <tr>
                    <td colSpan={10} className="bg-bg px-4 py-4 border-b border-line">
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        <TradeDetail trade={t} />
                        {t.filter_log && (
                          <FilterVisualizer
                            filters={t.filter_log}
                            title={`${t.strategy?.replace('_DAILY','')} · ${t.direction} Filters`}
                          />
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ExitBadge({ reason }: { reason?: string }) {
  if (!reason) return <span className="text-text3 text-xs">—</span>

  const cfg: Record<string, string> = {
    TARGET_HIT: 'bg-greenDim border-green/25 text-green',
    SL_HIT:     'bg-redDim border-red/25 text-red',
    TRAIL:      'bg-accentDim border-accent/25 text-accent',
    FORCE_EXIT: 'bg-amberDim border-amber/25 text-amber',
    EXPIRY:     'bg-amberDim border-amber/25 text-amber',
  }
  const key = Object.keys(cfg).find(k => reason.includes(k)) ?? ''
  return (
    <span className={clsx(
      'text-[11px] font-bold px-2 py-0.5 rounded border whitespace-nowrap',
      cfg[key] ?? 'bg-card border-line text-text3'
    )}>
      {reason.replace(/_/g,' ')}
    </span>
  )
}

function TradeDetail({ trade }: { trade: Trade }) {
  const cols = [
    ['Option', [
      ['Strike',   trade.strike ? `₹${trade.strike}` : '--'],
      ['Expiry',   trade.expiry ?? '--'],
      ['Lots',     String(trade.lots ?? '--')],
      ['Delta',    trade.delta_at_entry?.toFixed(3) ?? '--'],
    ]],
    ['Execution', [
      ['Entry',    trade.entry_ts?.slice(11,19) ?? '--'],
      ['Exit',     trade.exit_ts?.slice(11,19) ?? '--'],
      ['Spot',     trade.spot_at_entry ? `₹${trade.spot_at_entry.toFixed(0)}` : '--'],
      ['VIX',      trade.vix?.toFixed(2) ?? '--'],
    ]],
    ['P&L', [
      ['Gross',    trade.gross_pnl != null ? `₹${trade.gross_pnl.toFixed(2)}` : '--'],
      ['Charges',  trade.charges   != null ? `₹${trade.charges.toFixed(2)}`   : '--'],
      ['Net',      trade.net_pnl   != null ? `₹${trade.net_pnl.toFixed(2)}`   : '--'],
      ['Slippage', (trade as any).slippage_pct != null ? `${(trade as any).slippage_pct}%` : '--'],
    ]],
  ] as [string, [string,string][]][]

  return (
    <div className="bg-card rounded-xl border border-line p-4">
      <p className="text-sm font-semibold text-text1 mb-4">Trade Detail</p>
      <div className="grid grid-cols-3 gap-4">
        {cols.map(([title, rows]) => (
          <div key={title}>
            <p className="text-[11px] font-semibold tracking-widest uppercase text-text3 mb-3">{title}</p>
            <div className="space-y-2">
              {rows.map(([label, val]) => (
                <div key={label} className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-text3 whitespace-nowrap">{label}</span>
                  <span className="font-mono text-xs text-text1 font-medium text-right">{val}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
