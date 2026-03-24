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

    const statusInterval = setInterval(fetchBotStatus, 10000)

    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        store.setConnected(true)
        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, 30000)
        ;(ws as any)._ping = ping
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          store.setLastUpdate(new Date().toLocaleTimeString('en-IN'))

          if (msg.type === 'INIT' || msg.type === 'POSITION_UPDATE') {
            if (msg.position) store.setPosition(msg.position)
            if (msg.daily_pnl) store.setDailyPnl(msg.daily_pnl)
          }
          if (msg.events?.length) {
            store.addEvents(msg.events)
            fetchTrades()
            fetchDailyPnl()
            fetchSlippage()
            fetchBotStatus()
          }
        } catch {}
      }

      ws.onclose = () => {
        store.setConnected(false)
        clearInterval((ws as any)._ping)
        setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      clearInterval(statusInterval)
      wsRef.current?.close()
    }
  }, [])
}
