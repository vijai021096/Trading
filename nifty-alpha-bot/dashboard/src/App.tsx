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
      {/* Ambient orbs */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute top-[-20%] left-[10%] w-[600px] h-[600px] rounded-full bg-accent/[0.03] blur-[120px]" />
        <div className="absolute top-[30%] right-[-10%] w-[500px] h-[500px] rounded-full bg-cyan/[0.025] blur-[100px]" />
        <div className="absolute bottom-[-10%] left-[40%] w-[400px] h-[400px] rounded-full bg-green/[0.02] blur-[100px]" />
      </div>
      {/* Grid pattern */}
      <div className="fixed inset-0 pointer-events-none z-0 opacity-[0.02]"
        style={{ backgroundImage: 'linear-gradient(rgba(99,102,241,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,0.3) 1px, transparent 1px)', backgroundSize: '60px 60px' }}
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
