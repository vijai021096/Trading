import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, BarChart2, FlaskConical, Settings, AlertTriangle, WifiOff, Clock, ScrollText, Play, BookOpen, Radar } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'
import { NiftyTicker } from '../panels/NiftyTicker'
import axios from 'axios'
import clsx from 'clsx'

type Page = 'dashboard' | 'trades' | 'backtest' | 'watch' | 'logs' | 'replay' | 'journal' | 'settings'
const NAV: { id: Page; label: string; icon: typeof Activity }[] = [
  { id: 'dashboard', label: 'Live',      icon: Activity },
  { id: 'trades',    label: 'Trades',    icon: BarChart2 },
  { id: 'backtest',  label: 'Backtest',  icon: FlaskConical },
  { id: 'watch',     label: 'Watch',     icon: Radar },
  { id: 'logs',      label: 'Logs',      icon: ScrollText },
  { id: 'replay',    label: 'Replay',    icon: Play },
  { id: 'journal',   label: 'Journal',   icon: BookOpen },
  { id: 'settings',  label: 'Settings',  icon: Settings },
]

export function TopBar({ currentPage, onNavigate }: { currentPage: Page; onNavigate: (p: Page) => void }) {
  const { connected, dailyPnl, emergencyStop, setEmergencyStop } = useTradingStore()
  const [clock, setClock] = useState('')

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const pnl = dailyPnl?.net_pnl ?? 0
  const pnlPos = pnl >= 0
  const h = new Date().getHours()
  const m = new Date().getMinutes()
  const marketOpen = (h === 9 && m >= 15) || (h > 9 && h < 15) || (h === 15 && m <= 30)

  const handleStop = async () => {
    if (!emergencyStop) {
      if (!confirm('EMERGENCY STOP — halt all trading immediately?')) return
      await axios.post('/api/emergency-stop')
      setEmergencyStop(true)
    } else {
      await axios.delete('/api/emergency-stop')
      setEmergencyStop(false)
    }
  }

  return (
    <header className="sticky top-0 z-50 glass border-b border-line/30">
      <div className="flex items-center justify-between h-[64px] px-5 lg:px-8 max-w-[1640px] mx-auto">

        {/* Logo */}
        <div className="flex items-center gap-3 shrink-0">
          <motion.div className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #6366f1, #22d3ee)' }}
            whileHover={{ scale: 1.08, rotate: 3 }} whileTap={{ scale: 0.92 }}>
            <svg width="20" height="20" viewBox="0 0 16 16" fill="none">
              <polyline points="1,13 5,7 9,10 15,3" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="15" cy="3" r="2" fill="white"/>
            </svg>
          </motion.div>
          <div className="hidden sm:block">
            <div className="text-base font-black tracking-tight text-gradient leading-none">Nifty Alpha</div>
            <div className="text-[10px] font-bold tracking-[0.25em] text-text3 uppercase mt-0.5">Trading Terminal</div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex items-center gap-0.5 bg-surface/90 rounded-2xl p-1 border border-line/25 overflow-x-auto">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => onNavigate(id)}
              className={clsx('relative flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold transition-all whitespace-nowrap',
                currentPage === id ? 'text-text1' : 'text-text3 hover:text-text2')}>
              {currentPage === id && (
                <motion.div layoutId="tab" className="absolute inset-0 rounded-xl bg-card border border-accent/20"
                  transition={{ type: 'spring', stiffness: 500, damping: 35 }} />
              )}
              <span className="relative z-10 flex items-center gap-1.5">
                <Icon size={14} />
                <span className="hidden md:inline">{label}</span>
              </span>
            </button>
          ))}
        </nav>

        {/* Right */}
        <div className="flex items-center gap-3 shrink-0">
          {/* Live Nifty price */}
          <NiftyTicker />

          <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface/60 border border-line/20">
            <Clock size={12} className="text-text3" />
            <span className="font-mono text-sm text-text2 tabular-nums">{clock}</span>
          </div>

          <motion.div key={pnl.toFixed(0)} initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className={clsx('hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl text-sm font-bold font-mono border',
              pnlPos ? 'bg-green/10 border-green/20 text-green-l' : 'bg-red/10 border-red/20 text-red-l')}>
            <span className="text-text3 font-sans font-medium text-[10px] uppercase tracking-wider">P&L</span>
            {pnlPos ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN')}
          </motion.div>

          <div className={clsx('flex items-center gap-1.5', connected ? 'text-green' : 'text-text3')}>
            {connected ? (
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute h-full w-full rounded-full bg-green opacity-40"/>
                <span className="relative rounded-full h-2.5 w-2.5 bg-green glow-dot"/>
              </span>
            ) : <WifiOff size={14} />}
          </div>

          <motion.button onClick={handleStop} whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.92 }}
            className={clsx('flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border transition-all',
              emergencyStop ? 'bg-amber/15 text-amber border-amber/30 animate-pulse' : 'bg-red/10 text-red border-red/20 hover:bg-red/15')}>
            <AlertTriangle size={13} />
            <span className="hidden sm:inline">{emergencyStop ? 'HALT' : 'STOP'}</span>
          </motion.button>
        </div>
      </div>
    </header>
  )
}
