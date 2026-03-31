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
  signal_ltp?: number
  slippage_pct?: number
  entry_latency_ms?: number
  order_type?: string
  slm_order_id?: string
  sl_trigger_price?: number
  sl_fill_price?: number
  sl_slippage?: number
  sl_slippage_pct?: number
  sl_extra_loss?: number
  confidence?: number
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

export interface SlippageStats {
  total_sl_trades: number
  total_extra_loss: number
  avg_slippage_pct: number
  worst_slip: { date: string; symbol: string; slippage_pct: number; extra_loss: number } | null
  trades: Array<{
    date: string
    symbol: string
    trigger_price: number
    fill_price: number
    slippage: number
    slippage_pct: number
    extra_loss: number
  }>
}

export interface MarketState {
  trend_state: string | null
  trend_direction: string | null
  trend_conviction: number | null
  risk_multiplier: number | null
  strategy_priority: string[]
  trend_scores: Record<string, number>
  trend_impulse_grade: string | null
  regime: string | null
  regime_atr_ratio: number | null
  regime_adx: number | null
  regime_vix: number | null
  regime_rsi: number | null
}

export interface RuntimeOverride {
  max_trades?: number
  capital?: number
  lots?: number
  vix_max?: number
  strategy_filter?: string
  paper_mode?: boolean
  paused?: boolean
  force_close?: boolean
  halted?: boolean
}

export interface BotStatus {
  state: string
  market_status: string
  market_open: boolean
  thinking: string
  nifty_price: number | null
  nifty_open_price?: number
  move_from_open_pct?: number
  kite_connected: boolean
  kite_token_saved: boolean
  trades_today: number
  max_trades: number
  daily_pnl: number
  current_capital: number
  starting_capital: number
  peak_capital: number
  drawdown_pct: number
  max_drawdown_pct: number
  halt_active: boolean
  paused?: boolean
  force_close_pending?: boolean
  paper_mode: boolean
  trading_engine?: string
  daily_strategy_filter?: string
  consecutive_losses: number
  risk_per_trade_pct: number
  max_daily_loss_pct: number
  runtime_overrides?: RuntimeOverride
  daily_regime?: string
  active_engine?: string
  narrative?: string
  // Market intelligence fields (mirrored from HEARTBEAT)
  trend_state?: string | null
  trend_direction?: string | null
  trend_conviction?: number | null
  risk_multiplier?: number | null
  strategy_priority?: string[]
  trend_scores?: Record<string, number>
  trend_impulse_grade?: string | null
  regime?: string | null
  regime_atr_ratio?: number | null
  regime_adx?: number | null
  regime_vix?: number | null
  regime_rsi?: number | null
  last_scan: {
    strategies_evaluated: number
    signals_detected: number
    candidates: Array<{ strategy: string; signal: string; confidence: number }>
    scans: Array<{ strategy: string; signal: string | null; passed: boolean; confidence: number; regime?: string; lots?: number; sl_pct?: number; target_pct?: number }>
    vix?: number
    signal_bar_date?: string
  } | null
  position: Position | null
}

export interface StrategyConfig {
  capital: number
  lot_size: number
  vix_max: number
  max_trades_per_day: number
  max_daily_loss_pct: number
  max_daily_loss_hard: number
  max_drawdown_pct: number
  risk_per_trade_pct: number
  paper_mode: boolean
  orb_start: string
  orb_end: string
  entry_window_close: string
  reclaim_window_start: string
  reclaim_window_end: string
  trail_trigger_pct: number
  break_even_trigger_pct: number
  use_limit_orders: boolean
  use_slm_exit: boolean
  limit_price_buffer_pct: number
  sl_target_by_strategy: Record<string, { sl_pct: number; target_pct: number }>
  strategy_priority_by_trend: Record<string, string[]>
  backtest_stats: Record<string, { win_rate: number; profit_factor: number }>
  trading_engine?: string
  daily_strategy_filter?: string
  nifty_option_lot_size?: number
  daily_base_lots?: number
  daily_adaptive_window_start?: string
  daily_adaptive_window_end?: string
}

interface TradingStore {
  connected: boolean
  position: Position
  trades: Trade[]
  events: any[]
  dailyPnl: DailyPnL | null
  emergencyStop: boolean
  lastUpdate: string
  slippageStats: SlippageStats | null
  marketState: MarketState | null
  botStatus: BotStatus | null
  strategyConfig: StrategyConfig | null
  runtimeOverride: RuntimeOverride

  setConnected: (v: boolean) => void
  setPosition: (p: Position) => void
  setTrades: (t: Trade[]) => void
  addEvents: (e: any[]) => void
  setDailyPnl: (p: DailyPnL) => void
  setEmergencyStop: (v: boolean) => void
  setLastUpdate: (s: string) => void
  setSlippageStats: (s: SlippageStats) => void
  setMarketState: (m: MarketState) => void
  setBotStatus: (b: BotStatus) => void
  setStrategyConfig: (c: StrategyConfig) => void
  setRuntimeOverride: (r: RuntimeOverride) => void
}

export const useTradingStore = create<TradingStore>((set) => ({
  connected: false,
  position: { state: 'IDLE' },
  trades: [],
  events: [],
  dailyPnl: null,
  emergencyStop: false,
  lastUpdate: '',
  slippageStats: null,
  marketState: null,
  botStatus: null,
  strategyConfig: null,
  runtimeOverride: {},

  setConnected: (v) => set({ connected: v }),
  setPosition: (p) => set({ position: p }),
  setTrades: (t) => set({ trades: t }),
  addEvents: (e) => set((s) => ({ events: [...e, ...s.events].slice(0, 300) })),
  setDailyPnl: (p) => set({ dailyPnl: p }),
  setEmergencyStop: (v) => set({ emergencyStop: v }),
  setLastUpdate: (s) => set({ lastUpdate: s }),
  setSlippageStats: (s) => set({ slippageStats: s }),
  setMarketState: (m) => set({ marketState: m }),
  setBotStatus: (b) => set({ botStatus: b }),
  setStrategyConfig: (c) => set({ strategyConfig: c }),
  setRuntimeOverride: (r) => set({ runtimeOverride: r }),
}))
