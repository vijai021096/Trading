import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ArrowUpRight, ArrowDownRight, Clock, Filter as FilterIcon } from 'lucide-react'
import clsx from 'clsx'
import { Trade } from '../../stores/tradingStore'
import { FilterVisualizer } from './FilterVisualizer'

export function TradeLogTable({ trades, showDateCol = false }: { trades: Trade[]; showDateCol?: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(null)

  if (!trades.length) {
    return (
      <div className="glass-card rounded-2xl p-12 text-center">
        <BarChartIcon />
        <p className="text-text2 mt-3 font-medium">No trades yet</p>
        <p className="text-text3 text-[12px] mt-1">Trades appear here during market hours</p>
      </div>
    )
  }

  return (
    <div className="glass-card rounded-2xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-line/30">
              {showDateCol && <th className="text-left py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Date</th>}
              <th className="text-left py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Time</th>
              <th className="text-left py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Symbol</th>
              <th className="text-left py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Dir</th>
              <th className="text-right py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Entry</th>
              <th className="text-right py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Exit</th>
              <th className="text-left py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Reason</th>
              <th className="text-right py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">SL Slip</th>
              <th className="text-right py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">Latency</th>
              <th className="text-right py-3 px-4 text-[10px] font-bold tracking-wider text-text3 uppercase">P&L</th>
              <th className="w-8 py-3 px-3"></th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => {
              const isUp = t.net_pnl >= 0
              const isExp = expanded === i
              return (
                <motion.tr key={i} className={clsx('border-b border-line/15 hover:bg-card/50 transition-colors cursor-pointer group',
                  isExp && 'bg-card/60')}
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }}
                  onClick={() => setExpanded(isExp ? null : i)}>
                  {showDateCol && <td className="py-2.5 px-4 font-mono text-text3">{t.trade_date}</td>}
                  <td className="py-2.5 px-4 font-mono text-text2 whitespace-nowrap">{new Date(t.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</td>
                  <td className="py-2.5 px-4">
                    <div className="flex items-center gap-1.5">
                      <span className={clsx('w-1 h-4 rounded-full', t.option_type === 'CE' ? 'bg-green' : 'bg-red')} />
                      <span className="font-mono font-semibold text-text1">{t.symbol?.slice(-12) ?? t.strategy}</span>
                    </div>
                  </td>
                  <td className="py-2.5 px-4">
                    <span className={clsx('inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold',
                      t.direction === 'CALL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                      {t.direction === 'CALL' ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
                      {t.direction}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-right font-mono text-text2">₹{t.entry_price.toFixed(1)}</td>
                  <td className="py-2.5 px-4 text-right font-mono text-text2">{t.exit_price ? `₹${t.exit_price.toFixed(1)}` : '--'}</td>
                  <td className="py-2.5 px-4">
                    <span className={clsx('inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold',
                      t.exit_reason === 'TARGET' ? 'bg-green/10 text-green' :
                      t.exit_reason === 'SL_HIT' ? 'bg-red/10 text-red' : 'bg-surface text-text3')}>
                      {t.exit_reason?.replace(/_/g, ' ') ?? '--'}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-right font-mono">
                    {t.exit_reason === 'SL_HIT' && t.sl_slippage_pct != null ? (
                      <span className={clsx('font-bold text-[10px]', Math.abs(t.sl_slippage_pct) > 1 ? 'text-red' : 'text-amber')}>
                        {t.sl_slippage_pct > 0 ? '-' : '+'}{Math.abs(t.sl_slippage_pct).toFixed(1)}%
                      </span>
                    ) : <span className="text-text3 text-[10px]">--</span>}
                  </td>
                  <td className="py-2.5 px-4 text-right font-mono">
                    {t.entry_latency_ms != null ? (
                      <span className={clsx('font-bold text-[10px]', t.entry_latency_ms > 2000 ? 'text-red' : t.entry_latency_ms > 500 ? 'text-amber' : 'text-green')}>
                        {t.entry_latency_ms}ms
                      </span>
                    ) : <span className="text-text3 text-[10px]">--</span>}
                  </td>
                  <td className={clsx('py-2.5 px-4 text-right font-mono font-bold', isUp ? 'text-green' : 'text-red')}>
                    {isUp ? '+' : ''}₹{t.net_pnl.toLocaleString('en-IN')}
                  </td>
                  <td className="py-2.5 px-3">
                    <ChevronDown size={12} className={clsx('text-text3 transition-transform', isExp && 'rotate-180')} />
                  </td>
                </motion.tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BarChartIcon() {
  return (
    <div className="w-12 h-12 rounded-xl bg-surface border border-line/30 flex items-center justify-center mx-auto">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text3">
        <rect x="3" y="12" width="4" height="8" rx="1" /><rect x="10" y="8" width="4" height="12" rx="1" /><rect x="17" y="4" width="4" height="16" rx="1" />
      </svg>
    </div>
  )
}
