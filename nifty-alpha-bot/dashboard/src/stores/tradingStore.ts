import { create } from 'zustand'

export interface Trade {
  entry_ts: string
  exit_ts?: string
  symbol: string
  direction: string
  option_type: string
  strike: number
  expiry: string
  strategy: string
  lots: number
  entry_price: number
  exit_price?: number
  sl_price: number
  target_price: number
  exit_reason?: string
  gross_pnl?: number
  charges?: number
  net_pnl: number
  spot_at_entry: number
  vix: number
  trade_date: string
  filter_log?: Record<string, any>
}

export interface Position {
  state: string
  symbol?: string
  direction?: string
  strike?: number
  entry_price?: number
  sl_price?: number
  target_price?: number
  current_sl?: number
  net_pnl?: number
  lots?: number
  strategy?: string
  entry_time?: string
  highest_price_seen?: number
  break_even_set?: boolean
}

export interface DailyPnL {
  date: string
  trades: number
  wins: number
  losses: number
  net_pnl: number
  win_rate: number
}

interface TradingStore {
  connected: boolean
  position: Position
  trades: Trade[]
  events: any[]
  dailyPnl: DailyPnL | null
  emergencyStop: boolean
  lastUpdate: string

  setConnected: (v: boolean) => void
  setPosition: (p: Position) => void
  setTrades: (t: Trade[]) => void
  addEvents: (e: any[]) => void
  setDailyPnl: (p: DailyPnL) => void
  setEmergencyStop: (v: boolean) => void
  setLastUpdate: (s: string) => void
}

export const useTradingStore = create<TradingStore>((set) => ({
  connected: false,
  position: { state: 'IDLE' },
  trades: [],
  events: [],
  dailyPnl: null,
  emergencyStop: false,
  lastUpdate: '',

  setConnected: (v) => set({ connected: v }),
  setPosition: (p) => set({ position: p }),
  setTrades: (t) => set({ trades: t }),
  addEvents: (e) => set((s) => ({ events: [...e, ...s.events].slice(0, 200) })),
  setDailyPnl: (p) => set({ dailyPnl: p }),
  setEmergencyStop: (v) => set({ emergencyStop: v }),
  setLastUpdate: (s) => set({ lastUpdate: s }),
}))
