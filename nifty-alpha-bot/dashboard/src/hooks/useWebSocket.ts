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

  useEffect(() => {
    fetchTrades()
    fetchDailyPnl()

    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        store.setConnected(true)
        // Keep-alive ping
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
      wsRef.current?.close()
    }
  }, [])
}
