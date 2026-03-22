import { motion } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Target, ShieldCheck, BarChart3, Layers, Zap, ArrowUpRight, ArrowDownRight, Activity } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

export function LivePnLPanel() {
  const { position, dailyPnl, trades } = useTradingStore()
  const pnl      = dailyPnl?.net_pnl ?? 0
  const isActive = position.state === 'ACTIVE'
  const hasTrade = isActive || position.state === 'ENTRY_PENDING'
  const todayCount = dailyPnl?.trades ?? 0

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {/* P&L card - hero card */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}
        className={clsx('glass-card rounded-2xl p-4 border-l-[3px] relative overflow-hidden neon-border',
          pnl >= 0 ? 'border-l-green' : 'border-l-red')}>
        <div className={clsx('absolute -top-8 -right-8 w-24 h-24 rounded-full blur-2xl opacity-10', pnl >= 0 ? 'bg-green' : 'bg-red')} />
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold tracking-[0.18em] uppercase text-text3">Today's P&L</span>
            <div className={clsx('w-7 h-7 rounded-lg flex items-center justify-center', pnl >= 0 ? 'bg-green/10' : 'bg-red/10')}>
              {pnl >= 0 ? <TrendingUp size={13} className="text-green" /> : <TrendingDown size={13} className="text-red" />}
            </div>
          </div>
          <div className={clsx('text-[24px] font-extrabold leading-tight stat-val', pnl >= 0 ? 'text-green-l' : 'text-red-l')}>
            <CountUp end={Math.abs(pnl)} prefix={pnl >= 0 ? '+₹' : '-₹'} duration={0.8} separator="," preserveValue />
          </div>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-[11px] text-text3">{todayCount} trades</span>
            <span className="text-[11px] text-text3">·</span>
            <span className={clsx('text-[11px] font-semibold', (dailyPnl?.win_rate ?? 0) >= 50 ? 'text-green' : 'text-text3')}>
              {(dailyPnl?.win_rate ?? 0).toFixed(0)}% win
            </span>
            {todayCount > 0 && (
              <span className={clsx('inline-flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded',
                pnl >= 0 ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                {pnl >= 0 ? <ArrowUpRight size={9} /> : <ArrowDownRight size={9} />}
                {Math.abs(pnl / 1000).toFixed(1)}k
              </span>
            )}
          </div>
        </div>
      </motion.div>

      {/* Position card */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
        className={clsx('glass-card rounded-2xl p-4 border-l-[3px] relative overflow-hidden neon-border',
          isActive ? 'border-l-accent' : 'border-l-line')}>
        {isActive && <div className="absolute -top-8 -right-8 w-24 h-24 rounded-full bg-accent blur-2xl opacity-10" />}
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold tracking-[0.18em] uppercase text-text3">Position</span>
            <div className={clsx('w-7 h-7 rounded-lg flex items-center justify-center', isActive ? 'bg-accent/10' : 'bg-surface')}>
              {isActive ? <Zap size={13} className="text-accent" /> : <Target size={13} className="text-text3" />}
            </div>
          </div>
          <div className={clsx('text-lg font-extrabold stat-val', isActive ? 'text-accent-l' : 'text-text1')}>
            {hasTrade ? position.state : 'IDLE'}
          </div>
          <div className="text-[11px] text-text3 mt-1 truncate">
            {hasTrade ? (
              <span className="flex items-center gap-1.5">
                <span className={clsx('font-bold', position.direction === 'CALL' ? 'text-green' : 'text-red')}>{position.direction}</span>
                <span>·</span>
                <span className="font-mono">{position.symbol?.slice(-10) ?? ''}</span>
              </span>
            ) : 'Scanning for signals...'}
          </div>
        </div>
      </motion.div>

      {/* Win/Loss or SL→Target */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
        className="glass-card rounded-2xl p-4 border-l-[3px] border-l-line relative overflow-hidden neon-border">
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold tracking-[0.18em] uppercase text-text3">
              {isActive ? 'SL → Target' : 'Win / Loss'}
            </span>
            <div className="w-7 h-7 rounded-lg bg-surface flex items-center justify-center">
              {isActive ? <ShieldCheck size={13} className="text-accent" /> : <BarChart3 size={13} className="text-text3" />}
            </div>
          </div>
          {isActive ? (
            <>
              <div className="text-lg font-bold font-mono stat-val text-text1">
                <span className="text-red">₹{position.current_sl?.toFixed(0) ?? '--'}</span>
                <span className="text-text3 mx-1">→</span>
                <span className="text-green">₹{position.target_price?.toFixed(0) ?? '--'}</span>
              </div>
              <div className="text-[11px] mt-1">
                {position.break_even_set
                  ? <span className="text-green font-semibold flex items-center gap-1"><ShieldCheck size={10} /> BE locked</span>
                  : <span className="text-text3">Monitoring...</span>}
              </div>
            </>
          ) : (
            <>
              <div className="text-lg font-extrabold stat-val text-text1">
                <span className="text-green">{dailyPnl?.wins ?? 0}W</span>
                <span className="text-text3 mx-1">/</span>
                <span className="text-red">{dailyPnl?.losses ?? 0}L</span>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="flex-1 h-1.5 rounded-full bg-surface overflow-hidden">
                  <div className="h-full rounded-full bg-green transition-all duration-500" style={{ width: `${dailyPnl?.win_rate ?? 0}%` }} />
                </div>
                <span className="text-[10px] font-bold text-text3">{(dailyPnl?.win_rate ?? 0).toFixed(0)}%</span>
              </div>
            </>
          )}
        </div>
      </motion.div>

      {/* Trades / Strategy */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
        className="glass-card rounded-2xl p-4 border-l-[3px] border-l-line relative overflow-hidden neon-border">
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold tracking-[0.18em] uppercase text-text3">
              {isActive ? 'Strategy' : 'Trades Today'}
            </span>
            <div className="w-7 h-7 rounded-lg bg-surface flex items-center justify-center">
              <Layers size={13} className="text-text3" />
            </div>
          </div>
          <div className="text-lg font-extrabold stat-val text-text1">
            {isActive ? (position.strategy ?? '--') : `${todayCount} / 3`}
          </div>
          <div className="text-[11px] text-text3 mt-1">
            {isActive ? (
              <span>Entry <span className="font-mono font-bold text-text2">₹{position.entry_price?.toFixed(0) ?? '--'}</span></span>
            ) : (
              <span className="flex items-center gap-2">
                <span>Max 3/day</span>
                {todayCount >= 3 && <span className="text-amber font-bold">LIMIT</span>}
              </span>
            )}
          </div>
          {/* Usage dots */}
          <div className="flex gap-1 mt-2">
            {[0,1,2].map(i => (
              <div key={i} className={clsx('w-2 h-2 rounded-full transition-all', i < todayCount ? 'bg-accent glow-accent' : 'bg-surface border border-line/50')} />
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  )
}
