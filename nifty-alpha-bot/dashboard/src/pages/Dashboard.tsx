import { useEffect, useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import CountUp from 'react-countup'
import clsx from 'clsx'
import axios from 'axios'
import {
  Activity, Clock, Eye, AlertCircle, ArrowUpRight, ArrowDownRight,
  Crosshair, ShieldCheck, TrendingUp, TrendingDown, Radio, Layers,
  Zap, Target, BarChart3, LineChart, Gauge, Timer, Trophy, Flame,
  ChevronRight, Power, ToggleLeft, ToggleRight, AlertOctagon, Ruler
} from 'lucide-react'
import { AreaChart, Area, ResponsiveContainer, Tooltip } from 'recharts'
import { useTradingStore } from '../stores/tradingStore'

export function Dashboard() {
  const { position, trades, events, dailyPnl, connected, lastUpdate, emergencyStop } = useTradingStore()
  const isActive = position.state === 'ACTIVE'

  const todayTrades = useMemo(() =>
    trades.filter(t => t.trade_date === new Date().toISOString().slice(0, 10)), [trades])

  const cumulativePnl = useMemo(() => {
    let sum = 0
    return todayTrades.map(t => ({ time: new Date(t.entry_ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }), pnl: sum += t.net_pnl }))
  }, [todayTrades])

  const h = new Date().getHours()
  const m = new Date().getMinutes()
  const marketOpen = h >= 9 && (h < 15 || (h === 15 && m <= 30))
  const todayCount = dailyPnl?.trades ?? 0
  const pnl = dailyPnl?.net_pnl ?? 0

  const maxPnl = Math.max(...todayTrades.map(t => t.net_pnl), 0)
  const minPnl = Math.min(...todayTrades.map(t => t.net_pnl), 0)

  return (
    <div className="px-5 lg:px-8 py-6 max-w-[1640px] mx-auto space-y-5">

      {/* Market Status */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="glass rounded-2xl px-5 py-3 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <div className={clsx('flex items-center gap-2 px-3 py-1 rounded-xl text-xs font-bold uppercase tracking-wider',
            marketOpen ? 'bg-green/10 text-green' : 'bg-surface text-text3')}>
            <span className={clsx('w-2 h-2 rounded-full', marketOpen ? 'bg-green animate-pulse' : 'bg-text3')} />
            {marketOpen ? 'NSE Open' : 'Market Closed'}
          </div>
          <span className="text-sm text-text3 hidden sm:block">Session 9:15 AM – 3:30 PM IST</span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <Activity size={14} className={connected ? 'text-green' : 'text-red'} />
            <span className={clsx('font-semibold', connected ? 'text-green' : 'text-red')}>
              {connected ? 'Live Connected' : 'Disconnected'}
            </span>
          </div>
          {emergencyStop && (
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
              <span>·</span>
              <span className={clsx('font-semibold', (dailyPnl?.win_rate ?? 0) >= 50 ? 'text-green' : 'text-text3')}>
                {(dailyPnl?.win_rate ?? 0).toFixed(0)}% win
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
            <span className="text-green">{dailyPnl?.wins ?? 0}W</span>
            <span className="text-text3 mx-2">/</span>
            <span className="text-red">{dailyPnl?.losses ?? 0}L</span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
              <div className="h-full rounded-full bg-green transition-all duration-500" style={{ width: `${dailyPnl?.win_rate ?? 0}%` }} />
            </div>
            <span className="text-sm font-bold text-text2">{(dailyPnl?.win_rate ?? 0).toFixed(0)}%</span>
          </div>
        </motion.div>

        {/* Trades Today */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
          className="glass-card rounded-2xl p-5 border-l-[3px] border-l-line">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold tracking-widest uppercase text-text3">Trades Today</span>
            <Layers size={16} className="text-text3" />
          </div>
          <div className="text-2xl font-black text-text1">{todayCount} / 3</div>
          <div className="flex gap-2 mt-3">
            {[0,1,2].map(i => (
              <div key={i} className={clsx('flex-1 h-2 rounded-full transition-all',
                i < todayCount ? 'bg-accent glow-accent' : 'bg-surface')} />
            ))}
          </div>
          <div className="text-sm text-text3 mt-2">
            {todayCount >= 3 ? <span className="text-amber font-bold">LIMIT REACHED</span> : 'Max 3 per day'}
          </div>
        </motion.div>
      </div>

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
                    </div>
                  </div>
                  <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-bold border',
                    marketOpen ? 'bg-green/8 border-green/20 text-green' : 'bg-surface border-line/30 text-text3')}>
                    <Radio size={12} className={marketOpen ? 'animate-pulse' : ''} />
                    {marketOpen ? 'Scanning' : 'Offline'}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { name: 'ORB', desc: 'Opening Range Breakout', time: '9:30 – 10:00 AM', icon: Flame },
                    { name: 'VWAP', desc: 'VWAP Reclaim', time: '10:00 AM – 2:30 PM', icon: TrendingUp },
                  ].map(({ name, desc, time, icon: Icon }) => (
                    <div key={name} className="bg-surface/50 rounded-xl p-4 border border-line/20 hover:border-line/40 transition-all group">
                      <div className="flex items-center gap-2 mb-2">
                        <Icon size={16} className="text-accent" />
                        <span className="text-base font-bold text-text1">{name}</span>
                        <ChevronRight size={14} className="text-text3 ml-auto opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                      <div className="text-sm text-text3">{desc}</div>
                      <div className="text-xs text-text3 font-mono mt-1 flex items-center gap-1"><Timer size={11} /> {time}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </motion.div>

          {/* Intraday equity curve */}
          {cumulativePnl.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}
              className="glass-card rounded-2xl p-6 neon-border">
              <div className="flex items-center gap-2 mb-4">
                <LineChart size={16} className="text-accent" />
                <span className="text-sm font-bold uppercase tracking-widest text-text3">Intraday Equity</span>
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
                      formatter={(v: number) => [`₹${v.toLocaleString('en-IN')}`, 'P&L']} />
                  </AreaChart>
                </ResponsiveContainer>
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
                    {todayTrades.map((t, i) => (
                      <tr key={i} className="border-b border-line/10 hover:bg-card/40 transition-colors">
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
                        <td className={clsx('py-3 px-4 text-right font-mono font-bold', t.net_pnl >= 0 ? 'text-green' : 'text-red')}>
                          {t.net_pnl >= 0 ? '+' : ''}₹{t.net_pnl.toLocaleString('en-IN')}
                        </td>
                      </tr>
                    ))}
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
        </div>

        {/* Right 1/3 */}
        <div className="space-y-5">

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
                { label: 'Win Rate', value: `${(dailyPnl?.win_rate ?? 0).toFixed(0)}%`, color: (dailyPnl?.win_rate ?? 0) >= 50 ? 'text-green' : 'text-text3' },
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
              const lossLimit = 5000
              const riskPct = Math.min(100, Math.max(0, pnl < 0 ? (Math.abs(pnl) / lossLimit) * 100 : 0))
              const riskLevel = riskPct > 80 ? 'CRITICAL' : riskPct > 50 ? 'HIGH' : riskPct > 20 ? 'MODERATE' : 'LOW'
              const riskTextClass = riskPct > 50 ? 'text-red' : riskPct > 20 ? 'text-amber' : 'text-green'
              const riskBgClass = riskPct > 50 ? 'bg-red' : riskPct > 20 ? 'bg-amber' : 'bg-green'
              const riskBadgeClass = riskPct > 50 ? 'bg-red/15 text-red' : riskPct > 20 ? 'bg-amber/15 text-amber' : 'bg-green/15 text-green'
              return (
                <div className="space-y-4">
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

/* ── Nifty Live Price ──────────────────────────────────────── */
function NiftyChart() {
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
        <span className="text-xs text-text3">Live · 15s refresh</span>
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
function StrategyToggle() {
  const [state, setState] = useState({ orb_enabled: true, vwap_enabled: true })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    axios.get('/api/strategy/state').then(r => setState(r.data)).catch(() => {})
  }, [])

  const toggle = async (key: 'orb_enabled' | 'vwap_enabled') => {
    setLoading(true)
    try { const r = await axios.post('/api/strategy/toggle', { ...state, [key]: !state[key] }); setState(r.data) } catch {}
    setLoading(false)
  }

  const colorMap = {
    orb_enabled: {
      active: 'bg-amber/8 border-amber/20',
      inactive: 'bg-surface/50 border-line/20',
      icon: 'bg-amber/15',
      iconText: 'text-amber',
      toggle: 'text-amber',
    },
    vwap_enabled: {
      active: 'bg-cyan/8 border-cyan/20',
      inactive: 'bg-surface/50 border-line/20',
      icon: 'bg-cyan/15',
      iconText: 'text-cyan',
      toggle: 'text-cyan',
    },
  }

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
      className="glass-card rounded-2xl p-6 neon-border">
      <div className="flex items-center gap-2 mb-5">
        <Power size={16} className="text-accent" />
        <span className="text-sm font-bold uppercase tracking-widest text-text3">Strategy Control</span>
      </div>
      <div className="space-y-3">
        {([
          { key: 'orb_enabled' as const, label: 'ORB Strategy', desc: 'Opening Range Breakout · 9:30–10:00' },
          { key: 'vwap_enabled' as const, label: 'VWAP Reclaim', desc: 'VWAP Cross · 10:00–2:30' },
        ]).map(({ key, label, desc }) => {
          const cm = colorMap[key]
          return (
            <div key={key} className={clsx('flex items-center justify-between p-4 rounded-xl border transition-all',
              state[key] ? cm.active : cm.inactive)}>
              <div className="flex items-center gap-3">
                <div className={clsx('w-8 h-8 rounded-lg flex items-center justify-center', cm.icon)}>
                  <Zap size={14} className={cm.iconText} />
                </div>
                <div>
                  <div className="text-sm font-bold text-text1">{label}</div>
                  <div className="text-xs text-text3">{desc}</div>
                </div>
              </div>
              <button onClick={() => toggle(key)} disabled={loading}
                className={clsx('transition-all', loading && 'opacity-50')}>
                {state[key]
                  ? <ToggleRight size={28} className={cm.toggle} />
                  : <ToggleLeft size={28} className="text-text3" />}
              </button>
            </div>
          )
        })}
      </div>
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
