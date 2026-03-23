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
      const events = await axios.get(`${API_BASE}/events?limit=50`)
      const evts = events.data?.events || events.data || []
      const hb = evts.find((e: any) => e.event === 'HEARTBEAT')
      if (hb) {
        store.setBotStatus(hb)
        if (hb.trend_state) {
          store.setMarketState({
            trend_state: hb.trend_state,
            trend_direction: hb.trend_direction,
            trend_conviction: hb.trend_conviction,
            risk_multiplier: hb.risk_multiplier,
            strategy_priority: hb.strategy_priority || [],
            trend_scores: hb.trend_scores || {},
            regime: hb.regime,
            regime_atr_ratio: hb.regime_atr_ratio,
            regime_adx: hb.regime_adx,
            regime_vix: hb.regime_vix,
            regime_rsi: hb.regime_rsi,
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
