/**
 * PnlHero — big P&L display with win rate, trade count, and mini equity curve.
 */
import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import { AreaChart, Area, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { TrendingUp, TrendingDown, BarChart2, Percent, DollarSign } from 'lucide-react'
import { useTradingStore, Trade } from '../../stores/tradingStore'

function MiniChart({ trades }: { trades: Trade[] }) {
  const data = useMemo(() => {
    let running = 0
    return trades
      .slice()
      .sort((a, b) => (a.entry_ts ?? a.trade_date) < (b.entry_ts ?? b.trade_date) ? -1 : 1)
      .map(t => {
        running += Number(t.net_pnl ?? 0)
        return { pnl: Math.round(running) }
      })
  }, [trades])

  if (data.length < 2) return null

  const positive = data[data.length - 1]?.pnl >= 0
  const color = positive ? '#22c55e' : '#ef4444'

  return (
    <div className="h-16">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.35} />
              <stop offset="95%" stopColor={color} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <YAxis domain={['auto', 'auto']} hide />
          <Tooltip
            contentStyle={{ background: '#151c32', border: '1px solid #2a3460', borderRadius: 8, fontSize: 11 }}
            labelFormatter={() => ''}
            formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'P&L']}
          />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={color}
            strokeWidth={2}
            fill="url(#pnlGrad)"
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function Metric({ icon: Icon, label, value, color = 'text-text1', sub }: {
  icon: typeof BarChart2; label: string; value: React.ReactNode; color?: string; sub?: string
}) {
  return (
    <div className="flex items-center gap-3 bg-surface/50 rounded-xl px-3 py-2.5">
      <div className="w-8 h-8 rounded-lg bg-surface border border-line/30 flex items-center justify-center shrink-0">
        <Icon size={14} className="text-text3" />
      </div>
      <div>
        <div className={clsx('text-sm font-bold font-mono leading-tight', color)}>{value}</div>
        <div className="text-[10px] text-text3">{label}{sub && <span className="ml-1 text-text3/60">{sub}</span>}</div>
      </div>
    </div>
  )
}

export function PnlHero() {
  const { dailyPnl, trades, botStatus } = useTradingStore()

  const pnl     = dailyPnl?.net_pnl ?? botStatus?.daily_pnl ?? 0
  const wins    = dailyPnl?.wins ?? 0
  const losses  = dailyPnl?.losses ?? 0
  const total   = dailyPnl?.trades ?? 0
  const wr      = dailyPnl?.win_rate ?? 0
  const maxT    = botStatus?.max_trades ?? 4
  const capital = botStatus?.current_capital ?? botStatus?.starting_capital ?? 0
  const startCap = botStatus?.starting_capital ?? capital
  const capChg  = startCap ? ((capital - startCap) / startCap) * 100 : 0
  const pnlPos  = pnl >= 0

  return (
    <div className="glass-card rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={clsx('w-7 h-7 rounded-lg flex items-center justify-center',
            pnlPos ? 'bg-green/15' : 'bg-red/15'
          )}>
            {pnlPos ? <TrendingUp size={13} className="text-green" /> : <TrendingDown size={13} className="text-red" />}
          </div>
          <span className="text-xs font-bold uppercase tracking-widest text-text3">Today&rsquo;s P&amp;L</span>
        </div>
        <div className="text-[10px] font-mono text-text3">
          {total}/{maxT} trades
        </div>
      </div>

      {/* Hero number */}
      <AnimatePresence mode="popLayout">
        <motion.div
          key={Math.round(pnl)}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className={clsx(
            'text-4xl font-black tracking-tight font-mono',
            pnlPos ? 'text-green-l' : 'text-red-l'
          )}
        >
          {pnlPos ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </motion.div>
      </AnimatePresence>

      {/* Mini equity curve (all-time) */}
      {trades.length >= 2 && <MiniChart trades={trades} />}

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-2">
        <Metric
          icon={Percent} label="Win Rate" sub={`${wins}W ${losses}L`}
          value={`${wr.toFixed(0)}%`}
          color={wr >= 55 ? 'text-green' : wr >= 40 ? 'text-amber' : 'text-red-l'}
        />
        <Metric
          icon={DollarSign} label="Capital"
          value={`₹${Math.round(capital / 1000)}k`}
          color={capChg >= 0 ? 'text-green' : 'text-red-l'}
          sub={capChg !== 0 ? `${capChg >= 0 ? '+' : ''}${capChg.toFixed(1)}%` : undefined}
        />
      </div>
    </div>
  )
}