import React from 'react'
import { Activity, BarChart2, FlaskConical, Settings, AlertTriangle, Wifi, WifiOff } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'
import axios from 'axios'
import clsx from 'clsx'

type Page = 'dashboard' | 'trades' | 'backtest' | 'settings'

const NAV: { id: Page; label: string; icon: React.ComponentType<any> }[] = [
  { id: 'dashboard', label: 'Live',     icon: Activity },
  { id: 'trades',    label: 'Trades',   icon: BarChart2 },
  { id: 'backtest',  label: 'Backtest', icon: FlaskConical },
  { id: 'settings',  label: 'Settings', icon: Settings },
]

interface Props { currentPage: Page; onNavigate: (p: Page) => void }

export function TopBar({ currentPage, onNavigate }: Props) {
  const { connected, dailyPnl, emergencyStop, setEmergencyStop, lastUpdate } = useTradingStore()

  const pnl     = dailyPnl?.net_pnl ?? 0
  const pnlPos  = pnl >= 0

  const handleStop = async () => {
    if (!emergencyStop) {
      if (!confirm('Trigger EMERGENCY STOP? This halts all trading immediately.')) return
      await axios.post('/api/emergency-stop')
      setEmergencyStop(true)
    } else {
      await axios.delete('/api/emergency-stop')
      setEmergencyStop(false)
    }
  }

  return (
    <header className="sticky top-0 z-50 flex items-center justify-between h-14 px-5 bg-panel border-b border-line">

      {/* Logo */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <polyline points="1,13 5,8 9,10 15,3" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
            <circle cx="15" cy="3" r="1.8" fill="white"/>
          </svg>
        </div>
        <div className="leading-tight">
          <div className="text-sm font-bold text-text1 tracking-tight">Nifty Alpha</div>
          <div className="text-[10px] font-semibold tracking-widest text-text3 uppercase">Kite Bot</div>
        </div>
      </div>

      {/* Nav tabs */}
      <nav className="flex items-center gap-1 bg-bg rounded-xl p-1 border border-line">
        {NAV.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150',
              currentPage === id
                ? 'bg-card text-text1 shadow-sm border border-line'
                : 'text-text3 hover:text-text2 hover:bg-card/50'
            )}
          >
            <Icon size={13} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-3 shrink-0">

        {/* P&L badge */}
        <div className={clsx(
          'hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold font-mono',
          pnlPos
            ? 'bg-greenDim border-green/30 text-green'
            : 'bg-redDim border-red/30 text-red'
        )}>
          <span className="text-text3 font-sans font-medium">P&L</span>
          {pnlPos ? '+' : ''}₹{Math.abs(pnl).toLocaleString('en-IN')}
        </div>

        {/* Connection */}
        <div className="flex items-center gap-1.5">
          {connected
            ? <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green opacity-60"/>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green"/>
              </span>
            : <span className="h-2 w-2 rounded-full bg-text3"/>}
          <span className={clsx('text-xs font-semibold hidden lg:block', connected ? 'text-green' : 'text-text3')}>
            {connected ? 'Live' : 'Offline'}
          </span>
        </div>

        {/* Emergency stop */}
        <button
          onClick={handleStop}
          className={clsx(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold border transition-all',
            emergencyStop
              ? 'bg-amberDim text-amber border-amber/40 animate-pulse'
              : 'bg-redDim text-red border-red/30 hover:bg-red/20'
          )}
        >
          <AlertTriangle size={12} />
          <span className="hidden sm:inline">{emergencyStop ? 'ACTIVE' : 'STOP'}</span>
        </button>
      </div>
    </header>
  )
}
