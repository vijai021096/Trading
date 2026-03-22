import React, { useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { TopBar } from './components/layout/TopBar'
import { Dashboard } from './pages/Dashboard'
import { TradeHistory } from './pages/TradeHistory'
import { BacktestPage } from './pages/BacktestPage'
import { SettingsPage } from './pages/SettingsPage'

type Page = 'dashboard' | 'trades' | 'backtest' | 'settings'

export default function App() {
  useWebSocket()
  const [page, setPage] = useState<Page>('dashboard')

  return (
    <div className="flex flex-col min-h-screen bg-bg text-text1">
      <TopBar currentPage={page} onNavigate={setPage} />
      <main className="flex-1 overflow-auto">
        {page === 'dashboard' && <Dashboard />}
        {page === 'trades'    && <TradeHistory />}
        {page === 'backtest'  && <BacktestPage />}
        {page === 'settings'  && <SettingsPage />}
      </main>
    </div>
  )
}
