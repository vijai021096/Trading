import { useEffect, useRef } from 'react'
import { useTradingStore } from '../stores/tradingStore'
import axios from 'axios'

const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`
const API_BASE = '/api'

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const store = useTradingStore()

  const fetchTrades = async () => {
    try {
      const r = await axios.get(`${API_BASE}/trades?limit=200`)
      store.setTrades(r.data.trades || [])
    } catch {}
  }

  const fetchDailyPnl = async () => {
    try {
      const r = await axios.get(`${API_BASE}/pnl/daily`)
      store.setDailyPnl(r.data)
    } catch {}
  }

  const fetchSlippage = async () => {
    try {
      const r = await axios.get(`${API_BASE}/slippage/sl`)
      store.setSlippageStats(r.data)
    } catch {}
  }

  const fetchMarketState = async () => {
    try {
      const r = await axios.get(`${API_BASE}/market-state`)
      store.setMarketState(r.data)
    } catch {}
  }

  const fetchStrategyConfig = async () => {
    try {
      const r = await axios.get(`${API_BASE}/strategy/config`)
      store.setStrategyConfig(r.data)
    } catch {}
  }

  const fetchOverride = async () => {
    try {
      const r = await axios.get(`${API_BASE}/bot/override`)
      store.setRuntimeOverride(r.data)
    } catch {}
  }

  const fetchBotStatus = async () => {
    try {
      // /api/bot-status returns the latest HEARTBEAT event — full rich payload with
      // paper_mode, capital, kite_connected, trading_engine, skip_reasons, etc.
      const r = await axios.get(`${API_BASE}/bot-status`)
      const bs = r.data
      if (bs) {
        store.setBotStatus(bs)
        if (bs.trend_state) {
          store.setMarketState({
            trend_state: bs.trend_state,
            trend_direction: bs.trend_direction,
            trend_conviction: bs.trend_conviction,
            risk_multiplier: bs.risk_multiplier,
            strategy_priority: bs.strategy_priority || [],
            trend_scores: bs.trend_scores || {},
            regime: bs.regime,
            regime_atr_ratio: bs.regime_atr_ratio,
            regime_adx: bs.regime_adx,
            regime_vix: bs.regime_vix,
            regime_rsi: bs.regime_rsi,
            trend_impulse_grade: bs.trend_impulse_grade,
          })
        }
      }
    } catch {}
  }

  useEffect(() => {
    fetchTrades()
    fetchDailyPnl()
    fetchSlippage()
    fetchMarketState()
    fetchStrategyConfig()
    fetchBotStatus()
    fetchOverride()

    const statusInterval  = setInterval(fetchBotStatus, 8_000)
    const overrideInterval = setInterval(fetchOverride,  5_000)

    // Exponential backoff state
    let attempt       = 0
    let destroyed     = false
    let reconnTimeout: ReturnType<typeof setTimeout> | null = null

    function backoffMs() {
      // 2s → 4s → 8s → 16s → 30s (cap)
      return Math.min(2_000 * Math.pow(2, attempt), 30_000)
    }

    function connect() {
      if (destroyed) return
      let ws: WebSocket
      try {
        ws = new WebSocket(WS_URL)
      } catch {
        // URL construction failed (e.g., in tests)
        return
      }
      wsRef.current = ws

      let pingInterval: ReturnType<typeof setInterval> | null = null

      ws.onopen = () => {
        attempt = 0            // reset backoff on successful connect
        store.setConnected(true)
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 30_000)
      }

      ws.onmessage = (e) => {
        if (e.data === 'pong') return  // server keepalive
        try {
          const msg = JSON.parse(e.data)
          store.setLastUpdate(new Date().toLocaleTimeString('en-IN'))

          if (msg.type === 'INIT' || msg.type === 'POSITION_UPDATE') {
            if (msg.position)  store.setPosition(msg.position)
            if (msg.daily_pnl) store.setDailyPnl(msg.daily_pnl)
          }
          if (msg.events?.length) {
            store.addEvents(msg.events)
            if (msg.type !== 'INIT') {
              fetchTrades()
              fetchDailyPnl()
              fetchSlippage()
              fetchBotStatus()
            }
          }
        } catch {
          // Malformed message — ignore, don't crash
        }
      }

      ws.onclose = () => {
        store.setConnected(false)
        if (pingInterval) clearInterval(pingInterval)
        if (!destroyed) {
          attempt++
          const delay = backoffMs()
          reconnTimeout = setTimeout(connect, delay)
        }
      }

      ws.onerror = () => {
        // onclose fires after onerror, so just close to trigger backoff
        try { ws.close() } catch { /* ignore */ }
      }
    }

    connect()
    return () => {
      destroyed = true
      if (reconnTimeout) clearTimeout(reconnTimeout)
      clearInterval(statusInterval)
      clearInterval(overrideInterval)
      try { wsRef.current?.close() } catch { /* ignore */ }
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps
}
