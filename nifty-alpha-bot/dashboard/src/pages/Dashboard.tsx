/**
 * Dashboard — full trading terminal with all intelligence panels.
 * Layout: 3-column information-dense grid.
 */
import { useTradingStore } from '../stores/tradingStore'
import { BotBrain }        from '../components/panels/BotBrain'
import { TradePlan }       from '../components/panels/TradePlan'
import { NiftyLevels }     from '../components/panels/NiftyLevels'
import { PositionMonitor } from '../components/panels/PositionMonitor'
import { MarketIntel }     from '../components/panels/MarketIntel'
import { RiskPanel }       from '../components/panels/RiskPanel'
import { PnlHero }         from '../components/panels/PnlHero'
import { CommandCenter }   from '../components/panels/CommandCenter'
import { EventFeed }       from '../components/panels/EventFeed'
import { FilterVisualizer }from '../components/panels/FilterVisualizer'

export function Dashboard() {
  const { botStatus, position } = useTradingStore()
  const hasPosition = !!position?.symbol
  const filterLog   = (botStatus as any)?.last_scan_filters ?? {}

  return (
    <div className="flex-1 overflow-y-auto p-3 lg:p-4">
      {/* ── Row 1: Intelligence tier ────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
        {/* BotBrain — wide */}
        <div className="lg:col-span-1">
          <BotBrain />
        </div>

        {/* Today's plan — wide */}
        <div className="lg:col-span-1">
          <TradePlan />
        </div>

        {/* Nifty levels — narrow */}
        <div className="lg:col-span-1">
          <NiftyLevels />
        </div>
      </div>

      {/* ── Row 2: Position + Market + Risk ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
        <div className="lg:col-span-1">
          <PositionMonitor />
        </div>
        <div className="lg:col-span-1">
          <MarketIntel />
        </div>
        <div className="lg:col-span-1">
          <RiskPanel />
        </div>
      </div>

      {/* ── Row 3: Signal filters (if active scan) ──────────────── */}
      {Object.keys(filterLog).length > 0 && (
        <div className="mb-3">
          <FilterVisualizer filterLog={filterLog} />
        </div>
      )}

      {/* ── Row 4: P&L + Controls + Event Feed ──────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-1">
          <PnlHero />
        </div>
        <div className="lg:col-span-1">
          <CommandCenter />
        </div>
        <div className="lg:col-span-1" style={{ minHeight: '300px' }}>
          <EventFeed />
        </div>
      </div>
    </div>
  )
}