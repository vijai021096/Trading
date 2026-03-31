/**
 * NiftyTicker — live Nifty 50 price with change and move-from-open.
 * Polls /api/nifty/quote every 15s; shows graceful fallback from botStatus.
 */
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import axios from 'axios'
import { useTradingStore } from '../../stores/tradingStore'

interface Quote {
  price: number | null
  change: number | null
  change_pct: number | null
  error?: string
}

export function NiftyTicker() {
  const { botStatus } = useTradingStore()
  const [quote, setQuote] = useState<Quote | null>(null)

  // Poll live Kite quote; fall back to heartbeat nifty_price
  useEffect(() => {
    const fetch = async () => {
      try {
        const r = await axios.get<Quote>('/api/nifty/quote')
        if (r.data.price) setQuote(r.data)
      } catch {}
    }
    fetch()
    const id = setInterval(fetch, 15_000)
    return () => clearInterval(id)
  }, [])

  const price      = quote?.price ?? botStatus?.nifty_price ?? null
  const changePct  = quote?.change_pct ?? botStatus?.move_from_open_pct ?? null
  const change     = quote?.change ?? null

  if (!price) return null

  const up   = changePct != null && changePct > 0
  const dn   = changePct != null && changePct < 0
  const Icon = up ? TrendingUp : dn ? TrendingDown : Minus

  return (
    <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface/60 border border-line/20">
      <span className="text-[10px] font-bold text-text3 uppercase tracking-wide">NIFTY</span>
      <AnimatePresence mode="popLayout">
        <motion.span
          key={Math.round(price)}
          initial={{ opacity: 0.5, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="font-mono font-black text-sm text-text1 tabular-nums"
        >
          {price.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
        </motion.span>
      </AnimatePresence>
      {changePct != null && (
        <span className={clsx(
          'flex items-center gap-0.5 text-[11px] font-bold font-mono',
          up ? 'text-green' : dn ? 'text-red' : 'text-text3'
        )}>
          <Icon size={10} />
          {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
        </span>
      )}
    </div>
  )
}