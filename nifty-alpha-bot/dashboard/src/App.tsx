import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useWebSocket } from './hooks/useWebSocket'
import { TopBar } from './components/layout/TopBar'
import { Dashboard } from './pages/Dashboard'
import { TradeHistory } from './pages/TradeHistory'
import { BacktestPage } from './pages/BacktestPage'
import { SettingsPage } from './pages/SettingsPage'
import { LogsPage } from './pages/LogsPage'
import { WatchPage } from './pages/WatchPage'
import { TradeReplayPage } from './pages/TradeReplayPage'
import { JournalPage } from './pages/JournalPage'

type Page = 'dashboard' | 'trades' | 'backtest' | 'watch' | 'logs' | 'replay' | 'journal' | 'settings'

export default function App() {
  useWebSocket()
  const [page, setPage] = useState<Page>('dashboard')

  return (
    <div className="flex flex-col min-h-screen bg-bg text-text1 relative overflow-hidden">
      {/* Ambient orbs — amber terminal palette */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute top-[-20%] left-[5%] w-[700px] h-[700px] rounded-full bg-accent/[0.04] blur-[140px]" />
        <div className="absolute top-[25%] right-[-15%] w-[550px] h-[550px] rounded-full bg-cyan/[0.025] blur-[110px]" />
        <div className="absolute bottom-[-15%] left-[35%] w-[450px] h-[450px] rounded-full bg-green/[0.02] blur-[110px]" />
        <div className="absolute top-[60%] left-[-5%] w-[300px] h-[300px] rounded-full bg-accent/[0.02] blur-[80px]" />
      </div>
      {/* Subtle dot grid */}
      <div className="fixed inset-0 pointer-events-none z-0"
        style={{ backgroundImage: 'radial-gradient(circle, rgba(245,158,11,0.08) 1px, transparent 1px)', backgroundSize: '40px 40px' }}
      />

      <TopBar currentPage={page} onNavigate={setPage} />
      <main className="flex-1 overflow-auto relative z-10">
        <AnimatePresence mode="wait">
          <motion.div
            key={page}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          >
            {page === 'dashboard' && <Dashboard />}
            {page === 'trades'    && <TradeHistory />}
            {page === 'backtest'  && <BacktestPage />}
            {page === 'watch'    && <WatchPage />}
            {page === 'logs'      && <LogsPage />}
            {page === 'replay'    && <TradeReplayPage />}
            {page === 'journal'   && <JournalPage />}
            {page === 'settings'  && <SettingsPage />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
