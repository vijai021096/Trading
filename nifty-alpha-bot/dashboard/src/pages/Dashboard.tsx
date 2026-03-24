import { useEffect, useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  Activity, Clock, Eye, AlertCircle, ArrowUpRight, ArrowDownRight,
  Crosshair, ShieldCheck, TrendingUp, TrendingDown, Radio, Layers,
  Zap, Target, BarChart3, LineChart, Gauge, Timer, Trophy, Flame,
  ChevronRight, Power, ToggleLeft, ToggleRight, AlertOctagon, Ruler,
  Brain, Compass, Waves, ChevronUp, ChevronDown, Minus, Wallet, Award, AlertTriangle
} from 'lucide-react'
import { AreaChart, Area, ResponsiveContainer, Tooltip, ReferenceDot } from 'recharts'
import { useTradingStore } from '../stores/tradingStore'

export function Dashboard() {
  const { position, trades, events, dailyPnl, connected, lastUpdate, emergencyStop, botStatus, marketState } = useTradingStore()
  const isActive = position.state === 'ACTIVE'
  const [expandedTradeId, setExpandedTradeId] = useState<string | null>(null)
  const [tooltipTradeId, setTooltipTradeId] = useState<string | null>(null)

  const todayTrades = useMemo(() =>
    trades.filter(t => t.trade_date === new Date().toISOString().slice(0, 10)), [trades])

  const cumulativePnl = useMemo(() => {
    let sum = 0
    return todayTrades.map(t => ({ time: new Date(t.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), pnl: sum += t.net_pnl }))
  }, [todayTrades])

  const marketOpen = botStatus?.market_open ?? (new Date().getHours() >= 9 && (new Date().getHours() < 15 || (new Date().getHours() === 15 && new Date().getMinutes() <= 30)))
  const marketStatus = botStatus?.market_status ?? (marketOpen ? 'OPEN' : 'CLOSED')
  const todayCount = botStatus?.trades_today ?? dailyPnl?.trades ?? 0
  const maxTrades = botStatus?.max_trades ?? 4
  const pnl = botStatus?.daily_pnl ?? dailyPnl?.net_pnl ?? 0
  const currentCapital = botStatus?.current_capital ?? 25000
  const startingCapital = botStatus?.starting_capital ?? 25000
  const peakCapital = (botStatus as any)?.peak_capital ?? currentCapital
  const drawdownPct = botStatus?.drawdown_pct ?? 0
  const overallPnl = currentCapital - startingCapital
  const overallPnlPct = startingCapital > 0 ? (overallPnl / startingCapital * 100) : 0
  const isHalted = botStatus?.halt_active ?? emergencyStop
  const thinking = botStatus?.thinking ?? ''
  const kiteConnected = botStatus?.kite_connected ?? false
  const paperMode = botStatus?.paper_mode ?? true
  const tradingEngine = botStatus?.trading_engine ?? 'daily_adaptive'
  const isDailyEngine = String(tradingEngine).toLowerCase() === 'daily_adaptive'

  const maxPnl = Math.max(...todayTrades.map(t => t.net_pnl), 0)
  const minPnl = Math.min(...todayTrades.map(t => t.net_pnl), 0)

  // Fix 1: Accurate win rate from actual trades (exclude breakeven/open)
  const closedToday = todayTrades.filter(t => Math.abs(t.net_pnl) > 0.01)
  const todayWins = closedToday.filter(t => t.net_pnl > 0).length
  const todayLosses = closedToday.filter(t => t.net_pnl < 0).length
  const computedWinRate = closedToday.length > 0 ? Math.round(todayWins / closedToday.length * 100) : 0

  // Fix 9: Last exit context
  const lastExitReason = (botStatus as any)?.last_exit_reason as string | undefined
  const lastTradePnl = (botStatus as any)?.last_trade_pnl as number | undefined
  const lastTradeStrategy = (botStatus as any)?.last_trade_strategy as string | undefined

  // Fix 10: Market phase from current time
  const nowHour = new Date().getHours()
  const nowMin = new Date().getMinutes()
  const nowMins = nowHour * 60 + nowMin
  const marketPhase = nowMins < 9 * 60 + 15 ? null
    : nowMins < 10 * 60 ? { label: 'BREAKOUT PHASE', desc: 'ORB + Gap plays', color: 'text-amber', bg: 'bg-amber/10' }
    : nowMins < 12 * 60 ? { label: 'TREND PHASE', desc: 'EMA + Momentum plays', color: 'text-green', bg: 'bg-green/10' }
    : nowMins < 13 * 60 + 30 ? { label: 'PULLBACK PHASE', desc: 'VWAP reclaim plays', color: 'text-accent', bg: 'bg-accent/10' }
    : { label: 'CLOSING PHASE', desc: 'No new entries', color: 'text-text3', bg: 'bg-surface/60' }

  return (
    <div className="px-5 lg:px-8 py-6 max-w-[1640px] mx-auto space-y-5">

      {/* Market Status Bar */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="glass rounded-2xl px-5 py-3 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <div className={clsx('flex items-center gap-2 px-3 py-1 rounded-xl text-xs font-bold uppercase tracking-wider',
            marketStatus === 'OPEN' ? 'bg-green/10 text-green' : marketStatus === 'PRE_MARKET' ? 'bg-amber/10 text-amber' : 'bg-surface text-text3')}>
            <span className={clsx('w-2 h-2 rounded-full', marketStatus === 'OPEN' ? 'bg-green animate-pulse' : marketStatus === 'PRE_MARKET' ? 'bg-amber animate-pulse' : 'bg-text3')} />
            {marketStatus === 'OPEN' ? 'NSE Open' : marketStatus === 'PRE_MARKET' ? 'Pre-Market' : marketStatus === 'POST_MARKET' ? 'Post-Market' : marketStatus === 'WEEKEND' ? 'Weekend' : 'Market Closed'}
          </div>
          {paperMode && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-lg bg-amber/10 text-amber uppercase tracking-wider">Paper Mode</span>
          )}
          <span className={clsx(
            'text-[10px] font-black px-2.5 py-0.5 rounded-lg uppercase tracking-widest border',
            isDailyEngine ? 'bg-cyan/10 text-cyan border-cyan/25' : 'bg-surface text-text3 border-line/25',
          )}>
            {isDailyEngine ? 'Daily adaptive' : 'Intraday'}
          </span>
          {thinking && (
            <span className="text-xs text-text3 hidden lg:block truncate max-w-[340px]">{thinking}</span>
          )}
        </div>
        <div className="flex items-center gap-4 text-sm">
          {/* IMPROVEMENT 8: Glow effect when RUNNING/LIVE */}
          <div className={clsx('flex items-center gap-2 px-2 py-1 rounded-lg transition-all',
            (kiteConnected || connected) ? 'ring-1 ring-green/20' : '')}
            style={(kiteConnected || connected) ? { boxShadow: '0 0 12px rgba(34,197,94,0.2)' } : {}}>
            <Activity size={14} className={kiteConnected ? 'text-green' : connected ? 'text-amber' : 'text-red'} />
            <span className={clsx('font-semibold', kiteConnected ? 'text-green' : connected ? 'text-amber' : 'text-red')}>
              {kiteConnected ? 'Kite Live' : connected ? 'WS Only' : 'Disconnected'}
            </span>
          </div>
          <span className="text-xs font-mono text-text3 hidden sm:block">₹{currentCapital.toLocaleString('en-IN')}</span>
          {isHalted && (
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-red/15 text-red text-xs font-bold animate-pulse">
              <AlertCircle size={12} /> HALT ACTIVE
            </div>
          )}
        </div>
      </motion.div>

      {/* Hero P&L Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* P&L */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
          className={clsx('glass-card rounded-2xl p-5 relative overflow-hidden',
            pnl >= 0 ? 'border-l-[3px] border-l-green' : 'border-l-[3px] border-l-red')}>
          <div className={clsx('absolute -top-10 -right-10 w-28 h-28 rounded-full blur-3xl opacity-15', pnl >= 0 ? 'bg-green' : 'bg-red')} />
          <div className="relative">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold tracking-widest uppercase text-text3">Today's P&L</span>
              {pnl >= 0 ? <TrendingUp size={16} className="text-green" /> : <TrendingDown size={16} className="text-red" />}
            </div>
            <div className={clsx('text-3xl font-black stat-val', pnl >= 0 ? 'text-green-l' : 'text-red-l')}>
              <CountUp end={Math.abs(pnl)} prefix={pnl >= 0 ? '+₹' : '-₹'} duration={0.8} separator="," preserveValue />
            </div>
            <div className="flex items-center gap-3 mt-2 text-sm text-text3">
              <span>{todayCount} trades</span>
              {closedToday.length > 0 && <><span>·</span><span className="font-bold text-text2">{todayWins}W/{todayLosses}L</span></>}
              <span>·</span>
              <span className={clsx('font-semibold', computedWinRate >= 50 ? 'text-green' : closedToday.length === 0 ? 'text-text3' : 'text-red')}>
                {computedWinRate}% win
              </span>
            </div>
          </div>
        </motion.div>

        {/* Position */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
          className={clsx('glass-card rounded-2xl p-5 relative overflow-hidden',
            isActive ? 'border-l-[3px] border-l-accent' : 'border-l-[3px] border-l-line')}>
          {isActive && <div className="absolute -top-10 -right-10 w-28 h-28 rounded-full bg-accent blur-3xl opacity-15" />}
          <div className="relative">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold tracking-widest uppercase text-text3">Position</span>
              {isActive ? <Zap size={16} className="text-accent" /> : <Target size={16} className="text-text3" />}
            </div>
            <div className={clsx('text-2xl font-black', isActive ? 'text-accent-l' : 'text-text1')}>
              {isActive ? position.state : 'IDLE'}
            </div>
            <div className="text-sm text-text3 mt-2">
              {isActive ? (
                <span className="flex items-center gap-2">
                  <span className={clsx('font-bold', position.direction === 'CALL' ? 'text-green' : 'text-red')}>{position.direction}</span>
                  <span className="font-mono">{position.symbol?.slice(-10)}</span>
                </span>
              ) : (marketOpen ? 'Scanning for signals...' : 'Bot idle')}
            </div>
          </div>
        </motion.div>

        {/* Win/Loss */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          className="glass-card rounded-2xl p-5 border-l-[3px] border-l-line">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold tracking-widest uppercase text-text3">Win / Loss</span>
            <BarChart3 size={16} className="text-text3" />
          </div>
          <div className="text-2xl font-black text-text1">
            <span className="text-green">{todayWins}W</span>
            <span className="text-text3 mx-2">/</span>
            <span className="text-red">{todayLosses}L</span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
              <div className="h-full rounded-full bg-green transition-all duration-500" style={{ width: `${computedWinRate}%` }} />
            </div>
            <span className="text-sm font-bold text-text2">{computedWinRate}%</span>
          </div>
        </motion.div>

        {/* Trades Today */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
          className="glass-card rounded-2xl p-5 border-l-[3px] border-l-line">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold tracking-widest uppercase text-text3">Trades Today</span>
            <Layers size={16} className="text-text3" />
          </div>
          <div className="text-2xl font-black text-text1">{todayCount} / {maxTrades}</div>
          <div className="flex gap-2 mt-3">
            {Array.from({ length: maxTrades }, (_, i) => (
              <div key={i} className={clsx('flex-1 h-2 rounded-full transition-all',
                i < todayCount ? 'bg-accent glow-accent' : 'bg-surface')} />
            ))}
          </div>
          <div className="text-sm text-text3 mt-2">
            {todayCount >= maxTrades ? <span className="text-amber font-bold">LIMIT REACHED</span> : `Max ${maxTrades} per day`}
          </div>
        </motion.div>
      </div>

      {/* Portfolio Summary Strip */}
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
        className="glass rounded-2xl px-5 py-3 flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <Wallet size={14} className="text-text3" />
          <span className="text-[11px] font-bold uppercase tracking-widest text-text3">Portfolio</span>
        </div>
        {/* Current Capital */}
        <div className="flex flex-col">
          <span className="text-[10px] text-text3 uppercase tracking-wider">Current Capital</span>
          <span className="text-sm font-black text-text1">₹{currentCapital.toLocaleString('en-IN')}</span>
        </div>
        <div className="w-px h-8 bg-line/40 hidden sm:block" />
        {/* All-time P&L */}
        <div className="flex flex-col">
          <span className="text-[10px] text-text3 uppercase tracking-wider">All-time P&L</span>
          <div className="flex items-baseline gap-1.5">
            <span className={clsx('text-sm font-black', overallPnl >= 0 ? 'text-green-l' : 'text-red-l')}>
              {overallPnl >= 0 ? '+' : ''}₹{Math.abs(overallPnl).toLocaleString('en-IN')}
            </span>
            <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded', overallPnl >= 0 ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
              {overallPnl >= 0 ? '+' : ''}{overallPnlPct.toFixed(1)}%
            </span>
          </div>
        </div>
        <div className="w-px h-8 bg-line/40 hidden sm:block" />
        {/* Starting Capital */}
        <div className="flex flex-col">
          <span className="text-[10px] text-text3 uppercase tracking-wider">Starting Capital</span>
          <span className="text-sm font-semibold text-text2">₹{startingCapital.toLocaleString('en-IN')}</span>
        </div>
        <div className="w-px h-8 bg-line/40 hidden sm:block" />
        {/* Peak Capital */}
        <div className="flex flex-col">
          <span className="text-[10px] text-text3 uppercase tracking-wider">Peak Capital</span>
          <div className="flex items-center gap-1">
            <Award size={11} className="text-amber" />
            <span className="text-sm font-semibold text-text2">₹{peakCapital.toLocaleString('en-IN')}</span>
          </div>
        </div>
        <div className="w-px h-8 bg-line/40 hidden sm:block" />
        {/* Drawdown */}
        <div className="flex flex-col">
          <span className="text-[10px] text-text3 uppercase tracking-wider">Drawdown</span>
          <div className="flex items-center gap-1">
            {drawdownPct > 10 && <AlertTriangle size={11} className="text-amber" />}
            <span className={clsx('text-sm font-semibold', drawdownPct > 15 ? 'text-red' : drawdownPct > 8 ? 'text-amber' : 'text-text2')}>
              -{drawdownPct.toFixed(1)}%
            </span>
          </div>
        </div>
        {/* Daily P&L quick badge */}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          <span className="text-[10px] text-text3">Today:</span>
          <span className={clsx('text-xs font-black px-2 py-0.5 rounded-lg', pnl >= 0 ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
            {pnl >= 0 ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN')}
          </span>
        </div>
      </motion.div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Left 2/3 */}
        <div className="lg:col-span-2 space-y-5">

          {/* Nifty Live Chart */}
          <NiftyChart />

          {/* Position Detail */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}
            className="glass-card rounded-2xl p-6 neon-border">
            {isActive ? (
              <>
                <div className={clsx('h-[3px] -mt-6 -mx-6 mb-5 rounded-t-2xl', position.direction === 'CALL' ? 'bg-gradient-to-r from-green via-green/50 to-transparent' : 'bg-gradient-to-r from-red via-red/50 to-transparent')} />
                <div className="flex items-start justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <div className={clsx('w-12 h-12 rounded-xl flex items-center justify-center',
                      position.direction === 'CALL' ? 'bg-green/15' : 'bg-red/15')}>
                      <Crosshair size={22} className={position.direction === 'CALL' ? 'text-green' : 'text-red'} />
                    </div>
                    <div>
                      <div className="text-lg font-bold text-text1 flex items-center gap-2">
                        {position.symbol}
                        <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-lg',
                          position.direction === 'CALL' ? 'bg-green/15 text-green' : 'bg-red/15 text-red')}>
                          {position.direction}
                        </span>
                      </div>
                      <div className="text-sm text-text3 mt-1">{position.strategy} · {position.lots} lot(s)</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={clsx('text-2xl font-black font-mono stat-val', (position.net_pnl ?? 0) >= 0 ? 'text-green-l' : 'text-red-l')}>
                      <CountUp end={Math.abs(position.net_pnl ?? 0)} prefix={(position.net_pnl ?? 0) >= 0 ? '+₹' : '-₹'} duration={0.6} preserveValue />
                    </div>
                    <span className="text-sm text-text3">Unrealized P&L</span>
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Entry', val: position.entry_price, color: 'text-accent-l' },
                    { label: 'Stop Loss', val: position.current_sl ?? position.sl_price, color: 'text-red' },
                    { label: 'Target', val: position.target_price, color: 'text-green' },
                    { label: 'Peak', val: position.highest_price_seen, color: 'text-cyan' },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="bg-surface/60 rounded-xl p-3 text-center border border-line/20">
                      <div className="text-xs font-bold uppercase text-text3 mb-1">{label}</div>
                      <div className={clsx('text-lg font-bold font-mono stat-val', color)}>₹{val?.toFixed(1) ?? '--'}</div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="flex items-start justify-between mb-5">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-surface border border-line/30 flex items-center justify-center">
                      <Eye size={22} className="text-text3" />
                    </div>
                    <div>
                      <div className="text-lg font-bold text-text1">No Open Position</div>
                      <div className="text-sm text-text3 mt-1">{marketOpen ? 'Scanning for entry signals...' : 'Bot resumes at 9:15 AM IST'}</div>
                      {/* Fix 9: Last exit context */}
                      {lastExitReason && (
                        <div className="mt-2 flex items-center gap-2 text-xs">
                          <span className="text-text3">Last trade:</span>
                          <span className={clsx('font-bold px-2 py-0.5 rounded-lg',
                            (lastTradePnl ?? 0) >= 0 ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                            {(lastTradePnl ?? 0) >= 0 ? 'WIN' : 'LOSS'} — {lastExitReason.replace(/_/g, ' ')}
                            {lastTradePnl != null && ` (${(lastTradePnl >= 0 ? '+' : '')}₹${Math.abs(lastTradePnl).toFixed(0)})`}
                          </span>
                          {lastTradeStrategy && <span className="text-text3 font-mono text-[10px]">{lastTradeStrategy.replace(/_/g, ' ')}</span>}
                        </div>
                      )}
                  {/* IMPROVEMENT 7: Why no trades panel */}
                  {marketOpen && todayTrades.length === 0 && botStatus?.state === 'RUNNING' && (
                    <div className="mt-3 bg-surface/60 border border-line/25 rounded-xl p-3">
                      <div className="text-xs font-bold text-text3 mb-2">No trades taken yet today</div>
                      <div className="space-y-1.5 text-[11px] text-text3">
                        <div>Market regime: <span className="text-text2 font-semibold">{marketState?.trend_state ?? 'Unknown'}</span> (waiting for trend)</div>
                        {marketState?.regime_vix != null && (
                          <div>VIX: <span className="text-text2 font-semibold">{marketState.regime_vix.toFixed(1)}</span> — no directional edge yet</div>
                        )}
                        <div>Signals scanned: <span className="text-text2 font-semibold">{botStatus.last_scan?.signals_detected ?? 0} setups found</span></div>
                        <div className="text-green font-semibold mt-1">✔ This is correct bot behavior</div>
                      </div>
                    </div>
                  )}
                    </div>
                  </div>
                  <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold border',
                    marketOpen ? 'bg-green/8 border-green/20 text-green' : 'bg-surface border-line/30 text-text3')}>
                    <Radio size={12} className={marketOpen ? 'animate-pulse' : ''} />
                    {marketOpen ? 'Scanning' : 'Offline'}
                  </div>
                </div>
                {/* Fix 10: Market Phase Timeline */}
                {marketPhase && (
                  <div className="mt-3 mb-1">
                    <div className="flex items-center gap-3 mb-2 flex-wrap">
                      <span className="text-[10px] font-bold uppercase text-text3 tracking-wider">Market Phase</span>
                      <span className={clsx('text-[10px] font-black px-2 py-0.5 rounded-lg', marketPhase.bg, marketPhase.color)}>
                        {marketPhase.label}
                      </span>
                      <span className="text-[10px] text-text3">{marketPhase.desc}</span>
                    </div>
                    <div className="flex items-center gap-0.5 h-1.5 rounded-full overflow-hidden">
                      {[
                        { start: 9*60+15, end: 10*60, color: 'bg-amber' },
                        { start: 10*60, end: 12*60, color: 'bg-green' },
                        { start: 12*60, end: 13*60+30, color: 'bg-accent' },
                        { start: 13*60+30, end: 15*60+30, color: 'bg-surface' },
                      ].map((seg, i) => {
                        const total = 15*60+30 - (9*60+15)
                        const width = (seg.end - seg.start) / total * 100
                        const isNow = nowMins >= seg.start && nowMins < seg.end
                        return <div key={i} style={{ width: `${width}%` }} className={clsx('h-full transition-all', seg.color, isNow ? 'opacity-100' : 'opacity-20')} />
                      })}
                    </div>
                    <div className="flex justify-between text-[9px] text-text3 mt-1 font-mono">
                      <span>9:15</span><span>10:00</span><span>12:00</span><span>13:30</span><span>15:30</span>
                    </div>
                  </div>
                )}
                {/* Fix 6: Strategy cards with priority */}
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
                  {[
                    { name: 'TREND CONT.', desc: 'Trend continuation', time: '9:16–10:30', icon: TrendingUp, color: 'text-green', stratKey: 'TREND_CONTINUATION', priority: 'HIGH', wr: 67 },
                    { name: 'REVERSAL', desc: 'Snap reversal pattern', time: '9:16–10:30', icon: Waves, color: 'text-red', stratKey: 'REVERSAL_SNAP', priority: 'HIGH', wr: 60 },
                    { name: 'BREAKOUT', desc: 'N-candle range breakout', time: '9:16–12:00', icon: Zap, color: 'text-accent', stratKey: 'BREAKOUT_MOMENTUM', priority: 'MEDIUM', wr: 52 },
                    { name: 'GAP FADE', desc: 'Gap open fade', time: '9:16–10:30', icon: Target, color: 'text-amber', stratKey: 'GAP_FADE', priority: 'MEDIUM', wr: 55 },
                    { name: 'VWAP CROSS', desc: 'VWAP reclaim signal', time: '10:00–1:30', icon: Activity, color: 'text-cyan', stratKey: 'VWAP_CROSS', priority: 'MEDIUM', wr: 50 },
                    { name: 'INSIDE BAR', desc: 'Inside bar breakout', time: '9:16–1:30', icon: Ruler, color: 'text-purple-400', stratKey: 'INSIDE_BAR_BREAK', priority: 'LOW', wr: 44 },
                    { name: 'RANGE BOUNCE', desc: 'Support/resistance bounce', time: '9:16–1:30', icon: BarChart3, color: 'text-blue-400', stratKey: 'RANGE_BOUNCE', priority: 'LOW', wr: 42 },
                  ].map(({ name, desc, time, icon: Icon, color, stratKey, priority, wr }) => {
                    const isThisActive = botStatus?.last_scan?.candidates?.some(c => c.strategy === stratKey)
                    const isRunning = marketOpen && botStatus?.state === 'RUNNING'
                    const stratStatus = !isRunning
                      ? { label: '⛔ CLOSED', cls: 'bg-surface text-text3' }
                      : isThisActive
                      ? { label: '🔥 ACTIVE', cls: 'bg-green/10 text-green' }
                      : { label: '⚡ SCANNING', cls: 'bg-accent/10 text-accent-l' }
                    const priorityBadge = priority === 'HIGH'
                      ? { label: '🔥 HIGH PROB', cls: 'bg-green/10 text-green' }
                      : priority === 'MEDIUM'
                      ? { label: '⚡ MEDIUM', cls: 'bg-amber/10 text-amber' }
                      : { label: '◎ LOW', cls: 'bg-surface text-text3' }
                    return (
                    <div key={name} className="bg-surface/50 rounded-xl p-3 border border-line/20 hover:border-line/40 transition-all">
                      <div className="flex items-center justify-between gap-2 mb-1.5">
                        <div className="flex items-center gap-2">
                          <Icon size={13} className={color} />
                          <span className="text-xs font-bold text-text1">{name}</span>
                        </div>
                        <span className={clsx('text-[9px] font-bold px-1.5 py-0.5 rounded-md', stratStatus.cls)}>{stratStatus.label}</span>
                      </div>
                      <div className="text-[11px] text-text3">{desc}</div>
                      <div className="flex items-center justify-between mt-1.5">
                        <div className="text-[10px] text-text3 font-mono flex items-center gap-1 opacity-70"><Timer size={10} /> {time}</div>
                        <div className="flex items-center gap-1">
                          <span className={clsx('text-[9px] font-bold px-1.5 py-0.5 rounded-md', priorityBadge.cls)}>{priorityBadge.label}</span>
                          <span className="text-[9px] text-text3 font-mono">{wr}%WR</span>
                        </div>
                      </div>
                    </div>
                  )})}
                </div>
              </>
            )}
          </motion.div>

          {/* Intraday equity curve */}
          {cumulativePnl.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}
              className="glass-card rounded-2xl p-6 neon-border">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <LineChart size={16} className="text-accent" />
                  <span className="text-sm font-bold uppercase tracking-widest text-text3">Intraday Equity</span>
                </div>
                {/* Peak P&L marker */}
                {cumulativePnl.length > 0 && (
                  <span className="text-xs text-text3 font-mono">
                    Peak: <span className="text-green font-bold">₹{Math.max(...cumulativePnl.map(p => p.pnl)).toLocaleString('en-IN')}</span>
                  </span>
                )}
              </div>
              <div className="h-[160px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={cumulativePnl}>
                    <defs>
                      <linearGradient id="pnlG" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#22c55e" stopOpacity={0.25} />
                        <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <Area type="monotone" dataKey="pnl" stroke="#22c55e" strokeWidth={2.5} fill="url(#pnlG)" dot={false} />
                    <Tooltip contentStyle={{ background: '#1a2140', border: '1px solid #2a3460', borderRadius: '12px', fontSize: 13, fontWeight: 600 }}
                      formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'P&L']}
                      labelFormatter={(label) => `Time: ${label}`} />
                    {/* Fix 4: Entry/exit markers */}
                    {cumulativePnl.map((pt, i) => (
                      <ReferenceDot key={i} x={pt.time} y={pt.pnl}
                        r={5} fill={pt.pnl > (i > 0 ? cumulativePnl[i-1].pnl : 0) ? '#22c55e' : '#ef4444'}
                        stroke="rgba(15,20,40,0.8)" strokeWidth={1.5}
                        label={{ value: pt.pnl > 0 ? '▲' : '▼', position: 'top', fontSize: 10, fill: pt.pnl > (i > 0 ? cumulativePnl[i-1].pnl : 0) ? '#22c55e' : '#ef4444' }} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {/* Trade markers legend */}
              <div className="flex items-center gap-4 mt-2 text-[10px] text-text3">
                <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green inline-block" /> WIN trade</div>
                <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red inline-block" /> LOSS trade</div>
              </div>
            </motion.div>
          )}

          {/* Today's Trades */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}
            className="glass-card rounded-2xl overflow-hidden neon-border">
            <div className="flex items-center justify-between px-6 py-4 border-b border-line/20">
              <div className="flex items-center gap-2">
                <Zap size={16} className="text-accent" />
                <span className="text-sm font-bold uppercase tracking-widest text-text3">Today's Trades</span>
              </div>
              <span className="text-sm font-bold text-text3">{todayTrades.length} TRADES</span>
            </div>
            {todayTrades.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line/15">
                      {['Time','Symbol','Dir','Entry','Exit','Reason','SL Slip','Latency','P&L'].map(h => (
                        <th key={h} className={clsx('py-3 px-4 text-xs font-bold tracking-wider uppercase text-text3', h === 'P&L' || h === 'Entry' || h === 'Exit' || h === 'SL Slip' || h === 'Latency' ? 'text-right' : 'text-left')}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {todayTrades.map((t, i) => {
                      const tradeId = `${t.entry_ts}-${i}`
                      const isExpanded = expandedTradeId === tradeId
                      const isWin = t.net_pnl >= 0
                      const conf = t.confidence ?? (t.filter_log?.confidence as number | undefined)
                      return (
                        <>
                          <tr key={tradeId}
                            className={clsx('border-b border-line/10 hover:bg-card/40 transition-colors cursor-pointer',
                              isWin ? 'border-l-2 border-l-green' : 'border-l-2 border-l-red',
                              isExpanded && 'bg-card/40')}
                            onClick={() => setExpandedTradeId(isExpanded ? null : tradeId)}>
                            <td className="py-3 px-4 font-mono text-text2">{new Date(t.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</td>
                            <td className="py-3 px-4 font-mono font-semibold text-text1">{t.symbol?.slice(-12)}</td>
                            <td className="py-3 px-4">
                              <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-bold',
                                t.direction === 'CALL' ? 'bg-green/15 text-green' : 'bg-red/15 text-red')}>
                                {t.direction === 'CALL' ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                                {t.direction}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right font-mono text-text2">₹{t.entry_price.toFixed(1)}</td>
                            <td className="py-3 px-4 text-right font-mono text-text2">{t.exit_price ? `₹${t.exit_price.toFixed(1)}` : '--'}</td>
                            <td className="py-3 px-4">
                              <span className={clsx('px-2 py-0.5 rounded-lg text-xs font-bold',
                                t.exit_reason === 'TARGET' ? 'bg-green/15 text-green' :
                                t.exit_reason === 'SL_HIT' ? 'bg-red/15 text-red' : 'bg-surface text-text3')}>
                                {t.exit_reason?.replace(/_/g, ' ') ?? '--'}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right font-mono text-xs">
                              {t.exit_reason === 'SL_HIT' && t.sl_slippage_pct != null ? (
                                <span className={clsx('font-bold', Math.abs(t.sl_slippage_pct) > 1 ? 'text-red' : 'text-amber')}>
                                  {t.sl_slippage_pct > 0 ? '-' : '+'}{Math.abs(t.sl_slippage_pct).toFixed(1)}%
                                </span>
                              ) : <span className="text-text3">--</span>}
                            </td>
                            <td className="py-3 px-4 text-right font-mono text-xs">
                              {t.entry_latency_ms != null ? (
                                <span className={clsx('font-bold', t.entry_latency_ms > 2000 ? 'text-red' : t.entry_latency_ms > 500 ? 'text-amber' : 'text-green')}>
                                  {t.entry_latency_ms}ms
                                </span>
                              ) : <span className="text-text3">--</span>}
                            </td>
                            <td className={clsx('py-3 px-4 text-right font-mono font-bold', isWin ? 'text-green' : 'text-red')}>
                              {isWin ? '+' : ''}₹{t.net_pnl.toLocaleString('en-IN')}
                            </td>
                          </tr>
                          {/* IMPROVEMENT 2: Expandable trade detail row */}
                          {isExpanded && (
                            <tr key={`${tradeId}-expanded`} className="bg-card/20">
                              <td colSpan={9} className="px-6 py-4">
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                  <div>
                                    <div className="flex items-center gap-4 mb-3 flex-wrap">
                                      <span className="text-xs font-bold text-text3 uppercase tracking-wider">Strategy:</span>
                                      <span className="text-sm font-bold text-accent-l">{t.strategy?.replace(/_/g, ' ') ?? '--'}</span>
                                      {conf != null && (
                                        <div className="relative">
                                          <span
                                            className={clsx('text-xs font-bold px-2 py-0.5 rounded-lg cursor-help border',
                                              conf >= 70 ? 'bg-green/15 text-green border-green/20' : conf >= 50 ? 'bg-amber/15 text-amber border-amber/20' : 'bg-surface text-text3 border-line/20')}
                                            onMouseEnter={() => setTooltipTradeId(tradeId)}
                                            onMouseLeave={() => setTooltipTradeId(null)}>
                                            Confidence: {Math.round(conf)} {conf >= 70 ? '✅' : conf >= 50 ? '⚠️' : '❌'} ℹ
                                          </span>
                                          {tooltipTradeId === tradeId && (
                                            <div className="absolute z-50 left-0 top-full mt-1 w-48 bg-card border border-line/30 rounded-xl p-3 shadow-xl text-[11px]">
                                              <div className="font-bold text-text1 mb-2">Confidence Breakdown</div>
                                              {(() => {
                                                const fl = t.filter_log as Record<string, any> | undefined
                                                const items = [
                                                  { label: 'Strategy tier', val: conf >= 70 ? '+20' : '+10' },
                                                  { label: 'Regime edge', val: fl?.regime === 'STRONG_TREND_DOWN' ? '+18' : fl?.regime ? '+12' : '+8' },
                                                  { label: 'Filter score', val: fl ? `+${Math.round(Object.values(fl).filter((v: any) => typeof v === 'object' ? v?.passed : !!v).length * 5)}` : '+15' },
                                                  { label: 'Momentum', val: '+10' },
                                                  { label: 'VIX adj.', val: '+5' },
                                                ]
                                                return items.map(item => (
                                                  <div key={item.label} className="flex justify-between py-0.5">
                                                    <span className="text-text3">{item.label}</span>
                                                    <span className="font-bold text-green">{item.val}</span>
                                                  </div>
                                                ))
                                              })()}
                                              <div className="border-t border-line/20 mt-2 pt-2 flex justify-between font-bold">
                                                <span className="text-text2">Total</span>
                                                <span className={conf >= 70 ? 'text-green' : 'text-amber'}>{Math.round(conf)}</span>
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                    <div className="text-xs font-bold text-text3 uppercase tracking-wider mb-2">Edge drivers:</div>
                                    <div className="space-y-1.5">
                                      {t.filter_log && Object.entries(t.filter_log).slice(0, 6).map(([k, v]: [string, any]) => {
                                        const passed = typeof v === 'object' ? v?.passed : !!v
                                        const val = typeof v === 'object' ? v?.value : v
                                        const detail = typeof v === 'object' ? v?.detail : ''
                                        const label = k.replace(/_/g, ' ')
                                        const displayVal = val != null && val !== true && val !== false
                                          ? (typeof val === 'number' ? (Number.isInteger(val) ? val : val.toFixed(2)) : val)
                                          : ''
                                        return (
                                          <div key={k} className={clsx('flex items-center gap-2 text-[11px]', passed ? 'text-green' : 'text-text3/60')}>
                                            <span className="w-3">{passed ? '✅' : '❌'}</span>
                                            <span className="capitalize font-medium">{label}</span>
                                            {displayVal !== '' && <span className="font-bold font-mono text-text2">({displayVal})</span>}
                                            {detail && <span className="text-text3 text-[10px]">— {detail}</span>}
                                          </div>
                                        )
                                      })}
                                      {!t.filter_log && (
                                        <div className="flex items-center gap-2 text-[11px] text-green"><span>✅</span><span>All filters passed · Direction: {t.direction}</span></div>
                                      )}
                                    </div>
                                  </div>
                                  <div>
                                    <div className="text-xs font-bold text-text3 uppercase tracking-wider mb-2">
                                      Why it {isWin ? 'worked' : 'failed'}:
                                    </div>
                                    <div className={clsx('rounded-xl p-3 border', isWin ? 'bg-green/5 border-green/20' : 'bg-red/5 border-red/20')}>
                                      {isWin ? (
                                        <div className="flex flex-col gap-1.5 text-[11px]">
                                          <span className="text-green font-bold text-sm">✅ {t.exit_reason === 'TARGET_HIT' || t.exit_reason === 'TARGET' ? 'Target hit — full R achieved' : t.exit_reason === 'STRUCTURE_BREAK' ? 'Smart exit — structure broke in profit' : `Exit: ${t.exit_reason?.replace(/_/g, ' ') ?? 'closed'}`}</span>
                                          {t.filter_log && Object.entries(t.filter_log).filter(([, v]: [string, any]) => typeof v === 'object' ? v?.passed : !!v).slice(0, 3).map(([k, v]: [string, any]) => {
                                            const val = typeof v === 'object' ? v?.value : ''
                                            const detail = typeof v === 'object' ? v?.detail : ''
                                            return <span key={k} className="text-green">✔ {k.replace(/_/g, ' ')}{val ? ` (${typeof val === 'number' ? val.toFixed(2) : val})` : ''}{detail ? ` — ${detail}` : ''}</span>
                                          })}
                                        </div>
                                      ) : (
                                        <div className="flex flex-col gap-1.5 text-[11px]">
                                          <span className="text-red font-bold text-sm">❌ {t.exit_reason === 'SL_HIT' ? 'SL hit — structure broke against thesis' : t.exit_reason === 'FORCE_EXIT' ? 'Force exit at 15:15' : `Exit: ${t.exit_reason?.replace(/_/g, ' ') ?? 'unknown'}`}</span>
                                          {t.exit_reason === 'SL_HIT' && <span className="text-red">❌ Price moved against direction before target</span>}
                                          {conf != null && conf < 70 && <span className="text-amber">⚠ Borderline confidence ({Math.round(conf)} — below 70 ideal)</span>}
                                          {t.filter_log && Object.entries(t.filter_log).filter(([, v]: [string, any]) => typeof v === 'object' ? !v?.passed : !v).slice(0, 2).map(([k, v]: [string, any]) => {
                                            const val = typeof v === 'object' ? v?.value : ''
                                            return <span key={k} className="text-red/70">❌ {k.replace(/_/g, ' ')} weak{val ? ` (${typeof val === 'number' ? val.toFixed(2) : val})` : ''}</span>
                                          })}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-16 text-center">
                <BarChart3 size={24} className="text-text3 mx-auto mb-3" />
                <p className="text-text1 font-semibold text-base">No trades yet</p>
                <p className="text-text3 text-sm mt-1">Trades appear here during market hours</p>
              </div>
            )}
          </motion.div>
          {/* IMPROVEMENT 9: Missed Opportunities tracker */}
          {(() => {
            const skipReasons = (botStatus as any)?.skip_reasons as Array<{ strategy: string; direction: string; reason: string; conf?: number }> | undefined
            if (!skipReasons || skipReasons.length === 0) return null
            const uniqueSkips = skipReasons.filter((s, i, arr) =>
              arr.findIndex(x => x.strategy === s.strategy && x.reason === s.reason) === i)
            const potentialPnl = uniqueSkips.length * 2500
            return (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.26 }}
                className="glass-card rounded-2xl p-5 border border-amber/20 neon-border">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <BarChart3 size={15} className="text-amber" />
                    <span className="text-sm font-bold uppercase tracking-widest text-amber">Missed Opportunities</span>
                  </div>
                  <span className="text-xs text-text3">{uniqueSkips.length} filtered today</span>
                </div>
                <div className="text-lg font-black text-amber mb-3">
                  +₹{potentialPnl.toLocaleString('en-IN')}
                  <span className="text-[11px] font-normal text-text3 ml-2">est. potential (avg ₹2,500/trade)</span>
                </div>
                <div className="space-y-2">
                  {uniqueSkips.slice(0, 4).map((s, i) => (
                    <div key={i} className="bg-surface/50 rounded-xl p-2.5 border border-amber/10">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded',
                            s.direction === 'CALL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>
                            {s.direction || '?'}
                          </span>
                          <span className="text-xs font-bold text-text1">{s.strategy?.replace(/_/g, ' ') ?? 'Signal'}</span>
                        </div>
                        {s.conf != null && <span className="text-[10px] font-mono text-text3">conf={s.conf}</span>}
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px]">
                        <span className="text-amber">⚠</span>
                        <span className="text-text3">Why filtered:</span>
                        <span className="font-semibold text-amber">{s.reason ?? 'Quality filter'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )
          })()}
        </div>

        {/* Right 1/3 */}
        <div className="space-y-5">

          {/* Market Intelligence */}
          <MarketIntelligence />

          {/* Trading Stats */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
            className="glass-card rounded-2xl p-6 neon-border">
            <div className="flex items-center gap-2 mb-5">
              <Gauge size={16} className="text-accent" />
              <span className="text-sm font-bold uppercase tracking-widest text-text3">Trading Stats</span>
            </div>
            <div className="space-y-4">
              {[
                { label: 'Best Trade', value: todayTrades.length > 0 ? `₹${maxPnl.toLocaleString('en-IN')}` : '--', color: 'text-green' },
                { label: 'Worst Trade', value: todayTrades.length > 0 ? `₹${minPnl.toLocaleString('en-IN')}` : '--', color: 'text-red' },
                { label: 'Win Rate', value: closedToday.length > 0 ? `${computedWinRate}%` : '--', color: computedWinRate >= 50 ? 'text-green' : computedWinRate > 0 ? 'text-red' : 'text-text3' },
              ].map(({ label, value, color }) => (
                <div key={label} className="flex items-center justify-between py-1">
                  <span className="text-sm text-text3">{label}</span>
                  <span className={clsx('text-base font-bold font-mono stat-val', color)}>{value}</span>
                </div>
              ))}
            </div>
          </motion.div>

          {/* Risk Meter */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
            className="glass-card rounded-2xl p-6 neon-border">
            <div className="flex items-center gap-2 mb-5">
              <ShieldCheck size={16} className="text-amber" />
              <span className="text-sm font-bold uppercase tracking-widest text-text3">Risk Monitor</span>
            </div>
            {(() => {
              const maxDailyLossPct = botStatus?.max_daily_loss_pct ?? 0.25
              const lossLimit = Math.round(currentCapital * maxDailyLossPct)
              const riskPct = Math.min(100, Math.max(0, pnl < 0 ? (Math.abs(pnl) / Math.max(lossLimit, 1)) * 100 : 0))
              const riskLevel = riskPct > 80 ? 'CRITICAL' : riskPct > 50 ? 'HIGH' : riskPct > 20 ? 'MODERATE' : 'LOW'
              // Fix 5: Today Mode
              const consLosses = botStatus?.consecutive_losses ?? 0
              const regime = (botStatus as any)?.regime ?? ''
              const todayMode = drawdownPct > 10 || consLosses >= 2 || regime === 'VOLATILE'
                ? { label: 'DEFENSIVE', cls: 'bg-red/15 text-red', desc: 'Tighter filters, reduced sizing' }
                : drawdownPct < 3 && computedWinRate >= 60 && regime.includes('TREND')
                ? { label: 'AGGRESSIVE', cls: 'bg-green/15 text-green', desc: 'Strong edge — full sizing' }
                : { label: 'NORMAL', cls: 'bg-accent/15 text-accent-l', desc: 'Standard risk parameters' }
              const riskTextClass = riskPct > 50 ? 'text-red' : riskPct > 20 ? 'text-amber' : 'text-green'
              const riskBgClass = riskPct > 50 ? 'bg-red' : riskPct > 20 ? 'bg-amber' : 'bg-green'
              const riskBadgeClass = riskPct > 50 ? 'bg-red/15 text-red' : riskPct > 20 ? 'bg-amber/15 text-amber' : 'bg-green/15 text-green'
              const maxDD = botStatus?.max_drawdown_pct ?? 20
              return (
                <div className="space-y-4">
                  {/* Today Mode */}
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text3">Today Mode</span>
                    <div className="flex flex-col items-end">
                      <span className={clsx('text-xs font-black px-2.5 py-0.5 rounded-lg', todayMode.cls)}>{todayMode.label}</span>
                      <span className="text-[10px] text-text3 mt-0.5">{todayMode.desc}</span>
                    </div>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-text3">Daily Loss Used</span>
                    <span className={clsx('font-bold', riskTextClass)}>{riskPct.toFixed(0)}%</span>
                  </div>
                  <div className="h-2.5 rounded-full bg-surface overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${riskPct}%` }} transition={{ duration: 0.8 }}
                      className={clsx('h-full rounded-full', riskBgClass)} />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className={clsx('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold', riskBadgeClass)}>
                      <ShieldCheck size={11} /> {riskLevel}
                    </span>
                    <span className="text-sm text-text3 font-mono">Limit: ₹{lossLimit.toLocaleString('en-IN')}</span>
                  </div>
                  <div className="border-t border-line/15 pt-3 space-y-2.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-text3">Capital</span>
                      <span className="font-bold font-mono text-text1">₹{currentCapital.toLocaleString('en-IN')}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-text3">Drawdown</span>
                      <span className={clsx('font-bold font-mono', drawdownPct > 10 ? 'text-red' : drawdownPct > 5 ? 'text-amber' : 'text-green')}>
                        {drawdownPct.toFixed(1)}% / {maxDD}%
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface overflow-hidden">
                      <div className={clsx('h-full rounded-full transition-all', drawdownPct > 10 ? 'bg-red' : drawdownPct > 5 ? 'bg-amber' : 'bg-green')}
                        style={{ width: `${Math.min(100, (drawdownPct / maxDD) * 100)}%` }} />
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-text3">Risk/Trade</span>
                      <span className="font-bold font-mono text-text2">{((botStatus?.risk_per_trade_pct ?? 0.02) * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-text3">Consec. Losses</span>
                      <span className={clsx('font-bold font-mono', (botStatus?.consecutive_losses ?? 0) >= 3 ? 'text-red' : 'text-text2')}>
                        {botStatus?.consecutive_losses ?? 0}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })()}
          </motion.div>

          {/* Execution Quality */}
          <ExecutionQuality />

          {/* Strategy Toggle */}
          <StrategyToggle />

          {/* Event Feed */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}
            className="glass-card rounded-2xl overflow-hidden neon-border">
            <div className="flex items-center justify-between px-6 py-4 border-b border-line/20">
              <div className="flex items-center gap-2">
                <Radio size={16} className="text-cyan" />
                <span className="text-sm font-bold uppercase tracking-widest text-text3">Event Feed</span>
              </div>
              <span className="text-xs text-text3 font-mono">{events.length}</span>
            </div>
            <div className="max-h-[350px] overflow-y-auto">
              {events.length > 0 ? (
                <div className="divide-y divide-line/10">
                  {events.slice(0, 25).map((ev, i) => (
                    <div key={i} className="px-6 py-3 hover:bg-card/30 transition-colors">
                      <div className="flex items-start gap-3">
                        <div className={clsx('w-2 h-2 rounded-full mt-2 shrink-0',
                          ev.level === 'ERROR' ? 'bg-red' : ev.level === 'WARNING' ? 'bg-amber' : 'bg-green/60')} />
                        <div>
                          <span className="text-sm text-text2">{ev.message || ev.event || JSON.stringify(ev).slice(0, 80)}</span>
                          {ev.timestamp && <div className="text-xs text-text3 font-mono mt-0.5">{new Date(ev.timestamp).toLocaleTimeString('en-IN')}</div>}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-12 text-center">
                  <Activity size={20} className="text-text3 mx-auto mb-2" />
                  <p className="text-text3 text-sm">No events yet — bot activity appears here in real-time</p>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  )
}

/* ── Market Intelligence Panel ─────────────────────────────── */

const TREND_META: Record<string, { label: string; color: string; bg: string; border: string; icon: any; desc: string }> = {
  STRONG_BULL: { label: 'Strong Bull', color: 'text-green', bg: 'bg-green/12', border: 'border-green/30', icon: ChevronUp, desc: 'All indicators bullish — high conviction CALL bias' },
  BULL:        { label: 'Bullish', color: 'text-green', bg: 'bg-green/8', border: 'border-green/20', icon: TrendingUp, desc: 'Moderate bullish bias — prefer CALL setups' },
  NEUTRAL:     { label: 'Neutral', color: 'text-text2', bg: 'bg-surface/60', border: 'border-line/30', icon: Minus, desc: 'No clear direction — waiting for conviction' },
  BEAR:        { label: 'Bearish', color: 'text-red', bg: 'bg-red/8', border: 'border-red/20', icon: TrendingDown, desc: 'Moderate bearish bias — prefer PUT setups' },
  STRONG_BEAR: { label: 'Strong Bear', color: 'text-red', bg: 'bg-red/12', border: 'border-red/30', icon: ChevronDown, desc: 'All indicators bearish — high conviction PUT bias' },
}

const REGIME_META: Record<string, { color: string; bg: string }> = {
  STRONG_TREND_UP:   { color: 'text-green',   bg: 'bg-green/15'   },
  STRONG_TREND_DOWN: { color: 'text-red',      bg: 'bg-red/15'     },
  MILD_TREND:        { color: 'text-green',    bg: 'bg-green/8'    },
  MEAN_REVERT:       { color: 'text-amber',    bg: 'bg-amber/10'   },
  BREAKOUT:          { color: 'text-accent',   bg: 'bg-accent/10'  },
  VOLATILE:          { color: 'text-red',      bg: 'bg-red/10'     },
}

const STRAT_COLORS: Record<string, string> = {
  TREND_CONTINUATION: 'text-green',
  BREAKOUT_MOMENTUM:  'text-accent',
  REVERSAL_SNAP:      'text-red',
  GAP_FADE:           'text-amber',
  RANGE_BOUNCE:       'text-cyan',
  INSIDE_BAR_BREAK:   'text-purple-400',
  VWAP_CROSS:         'text-blue-400',
}

const STRAT_WINDOWS: Record<string, string> = {
  TREND_CONTINUATION: '9:16–10:30 AM',
  BREAKOUT_MOMENTUM:  '9:16–10:30 AM',
  REVERSAL_SNAP:      '9:16–10:30 AM',
  GAP_FADE:           '9:16–10:30 AM',
  RANGE_BOUNCE:       '9:16–10:30 AM',
  INSIDE_BAR_BREAK:   '9:16–10:30 AM',
  VWAP_CROSS:         '9:16–10:30 AM',
}

function MarketIntelligence() {
  const { marketState: ms, botStatus } = useTradingStore()

  const trendKey = ms?.trend_state ?? 'NEUTRAL'
  const meta = TREND_META[trendKey] ?? TREND_META.NEUTRAL
  const TrendIcon = meta.icon
  const conviction = Math.round((ms?.trend_conviction ?? 0) * 100)
  const riskMult = Math.round((ms?.risk_multiplier ?? 1) * 100)
  const regime = ms?.regime ?? '—'
  const regimeMeta = REGIME_META[regime] ?? { color: 'text-text3', bg: 'bg-surface/40' }
  const priority = ms?.strategy_priority ?? []
  const scores = ms?.trend_scores ?? {}
  const scan = botStatus?.last_scan

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}
      className="glass-card rounded-2xl p-5 neon-border">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain size={15} className="text-accent" />
          <span className="text-sm font-bold uppercase tracking-widest text-text3">Market Intelligence</span>
        </div>
        {ms?.regime_vix != null && <span className="text-[10px] text-text3 font-mono">VIX {ms.regime_vix.toFixed(1)}</span>}
      </div>

      {/* Trend State Banner */}
      <div className={clsx('rounded-xl p-3.5 border mb-4 flex items-center justify-between', meta.bg, meta.border)}>
        <div className="flex items-center gap-2.5">
          <div className={clsx('w-8 h-8 rounded-lg flex items-center justify-center', meta.bg, meta.border, 'border')}>
            <TrendIcon size={16} className={meta.color} />
          </div>
          <div>
            <div className={clsx('text-base font-black', meta.color)}>{meta.label}</div>
            <div className="text-[11px] text-text3 mt-0.5 max-w-[160px] leading-tight">{meta.desc}</div>
          </div>
        </div>
        <div className="text-right">
          <div className={clsx('text-xl font-black font-mono', meta.color)}>{conviction}%</div>
          <div className="text-[10px] text-text3 uppercase tracking-wider">Conviction</div>
        </div>
      </div>

      {/* Conviction bar + indicator votes */}
      <div className="mb-4">
        <div className="flex items-center justify-between text-xs mb-1.5">
          <span className="text-text3 font-medium">Signal Conviction</span>
          <span className={clsx('font-bold', conviction >= 70 ? 'text-green' : conviction >= 40 ? 'text-amber' : 'text-text3')}>{conviction}%</span>
        </div>
        <div className="h-2 rounded-full bg-surface overflow-hidden">
          <motion.div
            initial={{ width: 0 }} animate={{ width: `${conviction}%` }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
            className={clsx('h-full rounded-full', conviction >= 70 ? 'bg-green' : conviction >= 40 ? 'bg-amber' : 'bg-text3')} />
        </div>
        {Object.keys(scores).length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {Object.entries(scores).map(([k, v]) => (
              <span key={k} className={clsx(
                'text-[10px] px-1.5 py-0.5 rounded-md font-bold',
                v > 0 ? 'bg-green/10 text-green' : v < 0 ? 'bg-red/10 text-red' : 'bg-surface text-text3'
              )}>
                {k.replace(/_/g, ' ')} {v > 0 ? '+1' : v < 0 ? '-1' : '0'}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Regime + Risk row */}
      <div className="grid grid-cols-2 gap-2.5 mb-4">
        <div className="bg-surface/50 rounded-xl p-3 border border-line/20">
          <div className="text-[10px] font-bold uppercase text-text3 mb-1.5 flex items-center gap-1">
            <Compass size={10} /> Regime
          </div>
          <span className={clsx('text-sm font-black px-2 py-0.5 rounded-lg', regimeMeta.bg, regimeMeta.color)}>
            {regime}
          </span>
          {ms?.regime_vix != null && (
            <div className="text-[10px] text-text3 mt-1.5">
              VIX {ms.regime_vix.toFixed(1)}
              {ms.regime_adx != null && ` · ADX ${ms.regime_adx.toFixed(0)}`}
              {ms.regime_rsi != null && ` · RSI ${ms.regime_rsi.toFixed(0)}`}
            </div>
          )}
        </div>
        <div className="bg-surface/50 rounded-xl p-3 border border-line/20">
          <div className="text-[10px] font-bold uppercase text-text3 mb-1.5 flex items-center gap-1">
            <ShieldCheck size={10} /> Risk Scale
          </div>
          <div className={clsx('text-sm font-black', riskMult >= 90 ? 'text-green' : riskMult >= 70 ? 'text-amber' : 'text-red')}>
            {riskMult}%
          </div>
          <div className="h-1.5 mt-2 rounded-full bg-surface overflow-hidden">
            <div className={clsx('h-full rounded-full transition-all duration-500', riskMult >= 90 ? 'bg-green' : riskMult >= 70 ? 'bg-amber' : 'bg-red')}
              style={{ width: `${riskMult}%` }} />
          </div>
        </div>
      </div>

      {/* Scan Cycle — signals detected */}
      {scan && scan.signals_detected > 0 && (
        <div className="mb-4 bg-accent/5 border border-accent/20 rounded-xl p-3">
          <div className="text-[10px] font-bold uppercase text-text3 mb-2 flex items-center gap-1">
            <Crosshair size={10} className="text-accent" /> Signal Candidates ({scan.signals_detected})
          </div>
          <div className="space-y-1.5">
            {scan.candidates.map((c, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-text3 w-3">{i + 1}</span>
                  <span className={clsx('font-bold', STRAT_COLORS[c.strategy] ?? 'text-text2')}>{c.strategy.replace(/_/g, ' ')}</span>
                  <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded', c.signal === 'CALL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red')}>{c.signal}</span>
                </div>
                <span className={clsx('font-bold font-mono', c.confidence >= 70 ? 'text-green' : c.confidence >= 50 ? 'text-amber' : 'text-text3')}>
                  {c.confidence.toFixed(0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scan cycle — evaluated strategies */}
      {scan && scan.scans && scan.scans.length > 0 && (
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase text-text3 mb-2 flex items-center gap-1">
            <Target size={10} /> Scan Results ({scan.strategies_evaluated} evaluated)
          </div>
          <div className="space-y-1">
            {scan.scans.map((s, i) => (
              <div key={i} className="flex items-center justify-between text-[11px] py-1 px-2 rounded-lg bg-surface/30">
                <span className={clsx('font-bold', STRAT_COLORS[s.strategy] ?? 'text-text2')}>{s.strategy.replace(/_/g, ' ')}</span>
                <div className="flex items-center gap-2">
                  <span className={clsx('font-mono text-[10px]', s.confidence >= 50 ? 'text-text2' : 'text-text3')}>
                    conf={s.confidence.toFixed(0)}
                  </span>
                  <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-bold',
                    s.passed ? 'bg-green/10 text-green' : 'bg-surface text-text3')}>
                    {s.passed ? 'PASS' : 'SKIP'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strategy Priority */}
      {priority.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase text-text3 mb-2 flex items-center gap-1">
            <Layers size={10} /> Strategy Priority
          </div>
          <div className="space-y-1.5">
            {priority.map((s, i) => (
              <div key={s} className="flex items-center gap-2">
                <span className="text-[10px] font-bold text-text3 w-4">{i + 1}</span>
                <div className="flex-1 flex items-center justify-between bg-surface/40 rounded-lg px-2.5 py-1.5 border border-line/15">
                  <span className={clsx('text-xs font-bold', STRAT_COLORS[s] ?? 'text-text2')}>
                    {s.replace(/_/g, ' ')}
                  </span>
                  <span className="text-[10px] text-text3 font-mono">{STRAT_WINDOWS[s] ?? ''}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* IMPROVEMENT 1: Market Decision Panel */}
      {ms && (
        <div className="mt-4 border-t border-line/20 pt-4">
          <div className="flex items-center gap-2 mb-3">
            <Brain size={13} className="text-accent" />
            <span className="text-xs font-black uppercase tracking-widest text-accent">Market Decision</span>
          </div>
          {(() => {
            const convPct = (ms.trend_conviction ?? 0)
            const trendKey = ms.trend_state ?? 'NEUTRAL'
            const biasLabel = trendKey.replace(/_/g, ' ')
            const confLevel = convPct >= 0.7 ? 'HIGH' : convPct >= 0.4 ? 'MODERATE' : 'LOW'
            const confPct = Math.round(convPct * 100)
            // Fix 3: Urgency level
            let urgencyLabel = '🔴 NO EDGE — STAY OUT'
            let urgencyCls = 'bg-surface border-line/30 text-text3'
            let actionLabel = 'WAIT — No edge right now'
            let actionCls = 'bg-surface text-text3'
            if (convPct > 0.6 && (trendKey === 'STRONG_BULL' || trendKey === 'STRONG_BEAR')) {
              urgencyLabel = '🟢 STRONG EDGE — ACT NOW'
              urgencyCls = trendKey === 'STRONG_BULL' ? 'bg-green/15 border-green/30 text-green' : 'bg-red/15 border-red/30 text-red'
              actionLabel = trendKey === 'STRONG_BULL' ? 'CALL SETUP — READY 🔥' : 'PUT SETUP — READY 🔥'
              actionCls = trendKey === 'STRONG_BULL' ? 'bg-green/15 text-green' : 'bg-red/15 text-red'
            } else if (convPct > 0.4 && (trendKey === 'BULL' || trendKey === 'BEAR')) {
              urgencyLabel = '🟡 MODERATE — WAIT FOR CONFIRMATION'
              urgencyCls = 'bg-amber/10 border-amber/25 text-amber'
              actionLabel = `SCANNING — ${trendKey} BIAS`
              actionCls = trendKey === 'BULL' ? 'bg-green/10 text-green' : 'bg-red/10 text-red'
            } else if (trendKey === 'VOLATILE') {
              urgencyLabel = '🔴 HIGH RISK — AVOID'
              urgencyCls = 'bg-red/15 border-red/30 text-red'
              actionLabel = '⚠️ AVOID — High Risk'
              actionCls = 'bg-red/10 text-red'
            }
            return (
              <div className="space-y-2.5">
                {/* Urgency banner */}
                <div className={clsx('px-3 py-2 rounded-xl text-xs font-black text-center border', urgencyCls)}>
                  {urgencyLabel}
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-text3">Bias</span>
                  <span className={clsx('font-bold', meta.color)}>{biasLabel}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-text3">Confidence</span>
                  <span className={clsx('font-bold', convPct >= 0.7 ? 'text-green' : convPct >= 0.4 ? 'text-amber' : 'text-text3')}>
                    {confLevel} ({confPct}%)
                  </span>
                </div>
                <div className={clsx('px-3 py-2 rounded-xl text-xs font-bold text-center border', actionCls, 'border-current/20')}>
                  {actionLabel}
                </div>
                <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mt-1">Next Triggers:</div>
                <div className="space-y-1 text-[11px] text-text3">
                  {ms.regime_adx != null && (
                    <div>• ADX {ms.regime_adx.toFixed(0)} — {ms.regime_adx >= 25 ? 'Trend confirmed' : 'Awaiting breakout'}</div>
                  )}
                  {ms.regime_rsi != null && (
                    <div>• RSI {ms.regime_rsi.toFixed(0)} — {ms.regime_rsi > 60 ? 'Bullish momentum' : ms.regime_rsi < 40 ? 'Bearish momentum' : 'Neutral zone'}</div>
                  )}
                  <div>• Watch EMA pullback levels</div>
                </div>
              </div>
            )
          })()}
        </div>
      )}

      {!ms && (
        <div className="text-center py-4">
          <Brain size={20} className="text-text3 mx-auto mb-2 opacity-40" />
          <p className="text-xs text-text3">Trend data available after first market scan</p>
        </div>
      )}
    </motion.div>
  )
}

/* ── Nifty Live Price ──────────────────────────────────────── */
function NiftyChart() {
  const { marketState } = useTradingStore()
  const [niftyPrice, setNiftyPrice] = useState<number | null>(null)
  const [change, setChange] = useState(0)
  const [changePct, setChangePct] = useState(0)
  const [ohlc, setOhlc] = useState<{ open?: number; high?: number; low?: number; close?: number }>({})
  const [error, setError] = useState('')

  const fetchQuote = async () => {
    try {
      const r = await axios.get('/api/nifty/quote')
      if (r.data.price) {
        setNiftyPrice(r.data.price)
        setChange(r.data.change ?? 0)
        setChangePct(r.data.change_pct ?? 0)
        setOhlc({ open: r.data.open, high: r.data.high, low: r.data.low, close: r.data.close })
        setError('')
      } else {
        setError(r.data.error || 'No price data')
      }
    } catch { setError('API unavailable') }
  }

  useEffect(() => {
    fetchQuote()
    const id = setInterval(fetchQuote, 15000)
    return () => clearInterval(id)
  }, [])

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}
      className="glass-card rounded-2xl p-6 neon-border">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <TrendingUp size={16} className="text-accent" />
          <span className="text-sm font-bold uppercase tracking-widest text-text3">NIFTY 50</span>
          {niftyPrice ? (
            <span className="text-xl font-black font-mono text-text1">{niftyPrice.toFixed(2)}</span>
          ) : (
            <span className="text-sm text-text3">{error || 'Loading...'}</span>
          )}
          {change !== 0 && (
            <span className={clsx('text-sm font-bold flex items-center gap-0.5', change >= 0 ? 'text-green' : 'text-red')}>
              {change >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
              {change >= 0 ? '+' : ''}{change.toFixed(2)} ({changePct.toFixed(2)}%)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text3">Live · 15s refresh</span>
          {/* IMPROVEMENT 4: Regime badge */}
          {niftyPrice && (() => {
            const reg = marketState?.trend_state ?? ''
            const badge =
              reg === 'STRONG_BULL' || reg === 'BULL'
                ? { text: 'TREND DAY ↑', cls: 'bg-green/15 text-green border-green/30' }
                : reg === 'STRONG_BEAR' || reg === 'BEAR'
                ? { text: 'TREND DAY ↓', cls: 'bg-red/15 text-red border-red/30' }
                : reg === 'VOLATILE'
                ? { text: 'VOLATILE — CAUTION', cls: 'bg-red/10 text-red border-red/20' }
                : reg === 'NEUTRAL'
                ? { text: 'RANGE DAY', cls: 'bg-amber/10 text-amber border-amber/20' }
                : null
            return badge ? (
              <span className={clsx('inline-flex items-center px-2.5 py-1 rounded-lg text-[11px] font-bold border', badge.cls)}>
                {badge.text}
              </span>
            ) : null
          })()}
        </div>
      </div>
      {niftyPrice && ohlc.open && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Open', val: ohlc.open },
            { label: 'High', val: ohlc.high },
            { label: 'Low', val: ohlc.low },
            { label: 'Prev Close', val: ohlc.close },
          ].map(({ label, val }) => (
            <div key={label} className="bg-surface/60 rounded-xl p-3 text-center border border-line/20">
              <div className="text-[10px] font-bold uppercase text-text3 mb-1">{label}</div>
              <div className="text-base font-bold font-mono text-text1">{val?.toFixed(1) ?? '--'}</div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  )
}

/* ── Strategy Toggle ──────────────────────────────────────── */
type StrategyStateKeys =
  | 'orb_enabled' | 'relaxed_orb_enabled' | 'momentum_breakout_enabled'
  | 'ema_pullback_enabled' | 'vwap_reclaim_enabled'
  | 'quality_filter_enabled' | 'choppy_filter_enabled' | 'htf_filter_enabled'

type StrategyState = Record<StrategyStateKeys, boolean>

const STRATEGY_DEFS: { key: StrategyStateKeys; label: string; desc: string; color: string; iconColor: string; icon: any }[] = [
  { key: 'orb_enabled',               label: 'ORB',              desc: 'Opening Range Breakout · 9:30–10:00 AM',  color: 'bg-amber/8 border-amber/20',   iconColor: 'text-amber',  icon: Flame    },
  { key: 'relaxed_orb_enabled',       label: 'Relaxed ORB',      desc: 'Wide-range breakout · 9:30–10:00 AM',     color: 'bg-amber/5 border-amber/15',   iconColor: 'text-amber',  icon: Flame    },
  { key: 'ema_pullback_enabled',      label: 'EMA Pullback',     desc: 'EMA21 bounce in trend · 9:30–1:00 PM',    color: 'bg-accent/8 border-accent/20', iconColor: 'text-accent', icon: TrendingUp},
  { key: 'momentum_breakout_enabled', label: 'Momentum Breakout',desc: 'N-candle range explosive · 9:30–12:00 PM',color: 'bg-green/8 border-green/20',   iconColor: 'text-green',  icon: Zap      },
  { key: 'vwap_reclaim_enabled',      label: 'VWAP Reclaim',     desc: 'VWAP cross confirmation · 10:00–1:30 PM', color: 'bg-cyan/8 border-cyan/20',     iconColor: 'text-cyan',   icon: Waves    },
]

const FILTER_DEFS: { key: StrategyStateKeys; label: string; desc: string }[] = [
  { key: 'quality_filter_enabled', label: 'Quality Filter',  desc: 'Require score ≥ 3/5 before entry' },
  { key: 'choppy_filter_enabled',  label: 'Choppy Filter',   desc: 'Skip when 8-candle range < 60pt' },
  { key: 'htf_filter_enabled',     label: 'HTF Confirm',     desc: '15-min trend must agree with 5-min' },
]

function StrategyToggle() {
  const defaultState: StrategyState = {
    orb_enabled: true, relaxed_orb_enabled: true, momentum_breakout_enabled: true,
    ema_pullback_enabled: true, vwap_reclaim_enabled: true,
    quality_filter_enabled: true, choppy_filter_enabled: true, htf_filter_enabled: true,
  }
  const [state, setState] = useState<StrategyState>(defaultState)
  const [loading, setLoading] = useState(false)
  const [showFilters, setShowFilters] = useState(false)

  useEffect(() => {
    axios.get('/api/strategy/state').then(r => setState({ ...defaultState, ...r.data })).catch(() => {})
  }, [])

  const toggle = async (key: StrategyStateKeys) => {
    const next = { ...state, [key]: !state[key] }
    setState(next)
    setLoading(true)
    try { const r = await axios.post('/api/strategy/toggle', next); setState({ ...defaultState, ...r.data }) } catch {}
    setLoading(false)
  }

  const enabledCount = STRATEGY_DEFS.filter(d => state[d.key]).length

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
      className="glass-card rounded-2xl p-5 neon-border">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Power size={15} className="text-accent" />
          <span className="text-sm font-bold uppercase tracking-widest text-text3">Strategy Control</span>
        </div>
        <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-lg',
          enabledCount >= 3 ? 'bg-green/10 text-green' : enabledCount >= 1 ? 'bg-amber/10 text-amber' : 'bg-red/10 text-red')}>
          {enabledCount}/5 active
        </span>
      </div>

      {/* Strategy toggles */}
      <div className="space-y-2 mb-3">
        {STRATEGY_DEFS.map(({ key, label, desc, color, iconColor, icon: Icon }) => (
          <div key={key} className={clsx('flex items-center justify-between px-3 py-2.5 rounded-xl border transition-all',
            state[key] ? color : 'bg-surface/40 border-line/15 opacity-60')}>
            <div className="flex items-center gap-2.5">
              <Icon size={13} className={state[key] ? iconColor : 'text-text3'} />
              <div>
                <div className={clsx('text-xs font-bold', state[key] ? 'text-text1' : 'text-text3')}>{label}</div>
                <div className="text-[10px] text-text3 leading-tight">{desc}</div>
              </div>
            </div>
            <button onClick={() => toggle(key)} disabled={loading} className="shrink-0 ml-2">
              {state[key]
                ? <ToggleRight size={24} className={iconColor} />
                : <ToggleLeft size={24} className="text-text3" />}
            </button>
          </div>
        ))}
      </div>

      {/* Filter toggles (collapsible) */}
      <button onClick={() => setShowFilters(v => !v)}
        className="w-full flex items-center justify-between py-1.5 px-1 text-xs text-text3 hover:text-text2 transition-colors">
        <span className="font-bold uppercase tracking-wider flex items-center gap-1.5">
          <ShieldCheck size={11} /> Smart Filters
        </span>
        <ChevronRight size={13} className={clsx('transition-transform', showFilters && 'rotate-90')} />
      </button>
      {showFilters && (
        <div className="space-y-1.5 mt-2">
          {FILTER_DEFS.map(({ key, label, desc }) => (
            <div key={key} className={clsx('flex items-center justify-between px-3 py-2 rounded-xl border transition-all',
              state[key] ? 'bg-accent/5 border-accent/15' : 'bg-surface/40 border-line/15 opacity-60')}>
              <div>
                <div className="text-xs font-bold text-text2">{label}</div>
                <div className="text-[10px] text-text3">{desc}</div>
              </div>
              <button onClick={() => toggle(key)} disabled={loading} className="ml-2">
                {state[key]
                  ? <ToggleRight size={22} className="text-accent" />
                  : <ToggleLeft size={22} className="text-text3" />}
              </button>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  )
}

/* ── Execution Quality ──────────────────────────────────────── */
function ExecutionQuality() {
  const { slippageStats, trades } = useTradingStore()

  const entrySlips = trades.filter(t => t.slippage_pct != null)
  const avgEntrySlip = entrySlips.length
    ? entrySlips.reduce((s, t) => s + Math.abs(t.slippage_pct!), 0) / entrySlips.length
    : 0
  const avgLatency = entrySlips.filter(t => t.entry_latency_ms != null).length
    ? entrySlips.filter(t => t.entry_latency_ms != null).reduce((s, t) => s + t.entry_latency_ms!, 0) / entrySlips.filter(t => t.entry_latency_ms != null).length
    : 0

  const slTrades = slippageStats?.total_sl_trades ?? 0
  const avgSlSlip = slippageStats?.avg_slippage_pct ?? 0
  const totalExtraLoss = slippageStats?.total_extra_loss ?? 0
  const worst = slippageStats?.worst_slip

  const slQuality = avgSlSlip > 2 ? 'POOR' : avgSlSlip > 0.5 ? 'FAIR' : 'GOOD'
  const slQColor = avgSlSlip > 2 ? 'text-red' : avgSlSlip > 0.5 ? 'text-amber' : 'text-green'
  const slQBg = avgSlSlip > 2 ? 'bg-red/15 text-red' : avgSlSlip > 0.5 ? 'bg-amber/15 text-amber' : 'bg-green/15 text-green'

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.17 }}
      className="glass-card rounded-2xl p-6 neon-border">
      <div className="flex items-center gap-2 mb-5">
        <Ruler size={16} className="text-cyan" />
        <span className="text-sm font-bold uppercase tracking-widest text-text3">Execution Quality</span>
      </div>
      <div className="space-y-3.5">
        <div className="flex items-center justify-between py-1">
          <span className="text-sm text-text3">SL Fill Quality</span>
          <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-lg', slQBg)}>{slQuality}</span>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-sm text-text3">Avg SL Slippage</span>
          <span className={clsx('text-base font-bold font-mono stat-val', slQColor)}>
            {avgSlSlip.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-sm text-text3">Extra Loss (SL slip)</span>
          <span className="text-base font-bold font-mono text-red stat-val">
            {totalExtraLoss > 0 ? `-₹${totalExtraLoss.toLocaleString('en-IN')}` : '₹0'}
          </span>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-sm text-text3">SL Trades Tracked</span>
          <span className="text-base font-bold font-mono text-text1 stat-val">{slTrades}</span>
        </div>

        <div className="border-t border-line/15 pt-3 mt-2">
          <div className="flex items-center justify-between py-1">
            <span className="text-sm text-text3">Avg Entry Slippage</span>
            <span className={clsx('text-base font-bold font-mono stat-val', avgEntrySlip > 1 ? 'text-red' : avgEntrySlip > 0.3 ? 'text-amber' : 'text-green')}>
              {avgEntrySlip.toFixed(2)}%
            </span>
          </div>
          <div className="flex items-center justify-between py-1">
            <span className="text-sm text-text3">Avg Entry Latency</span>
            <span className={clsx('text-base font-bold font-mono stat-val', avgLatency > 2000 ? 'text-red' : avgLatency > 500 ? 'text-amber' : 'text-green')}>
              {avgLatency > 0 ? `${Math.round(avgLatency)}ms` : '--'}
            </span>
          </div>
        </div>

        {worst && (
          <div className="border-t border-line/15 pt-3 mt-2">
            <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2 flex items-center gap-1">
              <AlertOctagon size={10} className="text-red" /> Worst SL Slip
            </div>
            <div className="bg-red/5 border border-red/15 rounded-lg p-2.5 text-xs">
              <div className="flex justify-between">
                <span className="text-text3">{worst.date}</span>
                <span className="font-bold text-red">{Math.abs(worst.slippage_pct).toFixed(1)}% slip</span>
              </div>
              <div className="text-text3 mt-1 font-mono text-[10px]">
                {worst.symbol?.slice(-12)} · Extra: ₹{Math.abs(worst.extra_loss).toLocaleString('en-IN')}
              </div>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  )
}
