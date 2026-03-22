import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Settings, Key, Shield, CheckCircle2, XCircle, AlertCircle, Copy, Eye, EyeOff,
  RefreshCw, Loader2, BookOpen, Terminal, Globe, Lock, Zap, Clock, BarChart3,
  ChevronRight, Layers, SlidersHorizontal, Radio
} from 'lucide-react'

export function SettingsPage() {
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'idle' | 'ok' | 'error'>('idle')
  const [msg, setMsg] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [autoAuth, setAutoAuth] = useState(false)
  const [autoAuthStatus, setAutoAuthStatus] = useState<string>('')
  const [kiteLoading, setKiteLoading] = useState(false)

  useEffect(() => {
    axios.get('/api/kite/verify').then(r => {
      if (r.data.kite_connected) { setStatus('ok'); setMsg('Kite API connected') }
      else if (r.data.error) { setMsg(r.data.error) }
    }).catch(() => {})
  }, [])

  // Listen for postMessage from Kite OAuth popup
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'KITE_AUTH_OK') {
        setStatus('ok')
        const tp = e.data?.token_prefix || e.data?.token || ''
        setMsg(tp ? `Kite OK — token ${tp} saved` : 'Kite authenticated — token saved automatically')
        setKiteLoading(false)
      } else if (e.data?.type === 'KITE_AUTH_FAIL') {
        setStatus('error')
        setMsg(e.data?.error || 'Kite authentication failed')
        setKiteLoading(false)
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [])

  const loginToKite = async () => {
    setKiteLoading(true); setMsg(''); setStatus('idle')
    try {
      const r = await axios.get('/api/kite/auth-url')
      const url = r.data.url
      const w = 500, h = 700
      const left = window.screenX + (window.innerWidth - w) / 2
      const top = window.screenY + (window.innerHeight - h) / 2
      window.open(url, 'KiteLogin', `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no`)
    } catch (e: any) {
      setStatus('error')
      setMsg(e.response?.data?.detail || 'Failed to get Kite login URL — check KITE_API_KEY in .env')
      setKiteLoading(false)
    }
  }

  const saveToken = async () => {
    if (!token.trim()) return
    setSaving(true); setStatus('idle'); setMsg('')
    try {
      await axios.post('/api/kite/token', { access_token: token.trim() })
      setStatus('ok'); setMsg('Access token saved and verified')
    } catch (e: any) {
      setStatus('error'); setMsg(e.response?.data?.detail || 'Failed to save token')
    } finally { setSaving(false) }
  }

  const runAutoAuth = async () => {
    setAutoAuth(true); setAutoAuthStatus('Starting browser automation...')
    try {
      const r = await axios.post('/api/kite/auto-auth')
      setAutoAuthStatus(r.data.message || 'Authentication successful')
      setStatus('ok'); setMsg('Auto-authenticated successfully')
    } catch (e: any) {
      setAutoAuthStatus(e.response?.data?.detail || 'Auto-auth failed')
    } finally { setAutoAuth(false) }
  }

  return (
    <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
          <Settings size={18} className="text-accent" />
        </div>
        <div>
          <h1 className="text-lg font-extrabold text-text1 tracking-tight">Settings</h1>
          <p className="text-[11px] text-text3">Authentication, strategy parameters, and system config</p>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Left - Auth + Config */}
        <div className="lg:col-span-2 space-y-4">

          {/* Authentication */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Key size={13} className="text-accent" />
                </div>
                <span className="text-[12px] font-bold text-text1">Kite API Authentication</span>
              </div>
              <div className={clsx('flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-bold border',
                status === 'ok' ? 'bg-green/8 border-green/15 text-green' :
                status === 'error' ? 'bg-red/8 border-red/15 text-red' :
                'bg-surface border-line/30 text-text3')}>
                {status === 'ok' ? <CheckCircle2 size={10} /> : status === 'error' ? <XCircle size={10} /> : <Radio size={10} />}
                {status === 'ok' ? 'Connected' : status === 'error' ? 'Error' : 'Not Connected'}
              </div>
            </div>

            {/* One-click Kite Login */}
            <div className="space-y-4">
              <motion.button onClick={loginToKite} disabled={kiteLoading}
                whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                className={clsx('w-full flex items-center justify-center gap-3 px-5 py-3.5 rounded-xl text-[13px] font-bold border transition-all',
                  kiteLoading ? 'bg-green/10 text-green border-green/20' :
                  'bg-gradient-to-r from-green/90 to-green text-white border-green hover:shadow-lg hover:shadow-green/20')}>
                {kiteLoading ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
                {kiteLoading ? 'Waiting for Kite login...' : 'Login to Kite (One-Click)'}
              </motion.button>
              <p className="text-[10px] text-text3 text-center">Opens Kite login in a popup. After you authenticate, the token is saved automatically.</p>

              <div className="border-t border-line/15 pt-3">
                <div className="text-[10px] font-bold text-text3 uppercase tracking-wider mb-2">Or paste token manually</div>
                <div className="relative">
                  <input
                    type={showToken ? 'text' : 'password'}
                    value={token}
                    onChange={e => setToken(e.target.value)}
                    placeholder="Paste your Kite access token..."
                    className="w-full bg-surface border border-line/30 rounded-xl pl-3 pr-20 py-2.5 text-[12px] text-text1 font-mono focus:border-accent/40 focus:outline-none transition-colors placeholder:text-text3/50"
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                    <button onClick={() => setShowToken(!showToken)} className="p-1.5 text-text3 hover:text-text2 transition-colors rounded-lg hover:bg-card">
                      {showToken ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                    <button onClick={() => navigator.clipboard.readText().then(t => setToken(t))} className="p-1.5 text-text3 hover:text-text2 transition-colors rounded-lg hover:bg-card">
                      <Copy size={12} />
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <motion.button onClick={saveToken} disabled={saving || !token.trim()}
                    whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                    className={clsx('flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-bold border transition-all',
                      saving ? 'bg-accent/10 text-accent border-accent/20' :
                      token.trim() ? 'bg-accent text-white border-accent hover:shadow-lg hover:shadow-accent/20' :
                      'bg-surface text-text3 border-line/30 cursor-not-allowed')}>
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Shield size={12} />}
                    {saving ? 'Verifying...' : 'Save & Verify'}
                  </motion.button>

                  <motion.button onClick={runAutoAuth} disabled={autoAuth}
                    whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                    className={clsx('flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-bold border transition-all',
                      autoAuth ? 'bg-cyan/10 text-cyan border-cyan/20' : 'bg-surface text-text2 border-line/30 hover:border-cyan/30 hover:text-cyan')}>
                    {autoAuth ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    Auto-Auth (TOTP)
                  </motion.button>
                </div>
              </div>

              <AnimatePresence>
                {(msg || autoAuthStatus) && (
                  <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
                    className={clsx('flex items-center gap-2 px-3 py-2 rounded-lg text-[11px]',
                      status === 'ok' ? 'bg-green/8 text-green' : status === 'error' ? 'bg-red/8 text-red' : 'bg-surface text-text2')}>
                    {status === 'ok' ? <CheckCircle2 size={12} /> : status === 'error' ? <AlertCircle size={12} /> : <RefreshCw size={12} />}
                    {msg || autoAuthStatus}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Strategy Parameters */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
            className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
                <SlidersHorizontal size={13} className="text-cyan" />
              </div>
              <span className="text-[12px] font-bold text-text1">Strategy Parameters</span>
              <span className="text-[9px] font-bold text-text3 bg-surface px-2 py-0.5 rounded-lg border border-line/20 uppercase tracking-wider">Read-only</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* ORB params */}
              <div className="rounded-xl border border-line/20 p-4 bg-surface/30">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-5 h-5 rounded bg-amber/10 flex items-center justify-center">
                    <Zap size={10} className="text-amber" />
                  </div>
                  <span className="text-[11px] font-bold text-text1">ORB Strategy</span>
                </div>
                <div className="space-y-2">
                  {[
                    ['Window', '9:15 – 9:30 AM'],
                    ['Breakout Buffer', '0.1%'],
                    ['Stop Loss', '50% of ORB range'],
                    ['Target', '2× SL'],
                    ['Max Trades', '1 per session'],
                    ['Trailing SL', 'After 1:1 R:R'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center">
                      <span className="text-[11px] text-text3">{k}</span>
                      <span className="text-[11px] font-bold font-mono text-text1">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
              {/* VWAP params */}
              <div className="rounded-xl border border-line/20 p-4 bg-surface/30">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-5 h-5 rounded bg-cyan/10 flex items-center justify-center">
                    <BarChart3 size={10} className="text-cyan" />
                  </div>
                  <span className="text-[11px] font-bold text-text1">VWAP Strategy</span>
                </div>
                <div className="space-y-2">
                  {[
                    ['Active Window', '10:00 AM – 2:30 PM'],
                    ['Reclaim Threshold', '±0.05%'],
                    ['Volume Confirm', '1.2× average'],
                    ['Stop Loss', '0.3% from VWAP'],
                    ['Target', '2× SL'],
                    ['Max Trades', '2 per session'],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center">
                      <span className="text-[11px] text-text3">{k}</span>
                      <span className="text-[11px] font-bold font-mono text-text1">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </motion.div>

          {/* Risk Management */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
            className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-red/10 flex items-center justify-center">
                <Shield size={13} className="text-red" />
              </div>
              <span className="text-[12px] font-bold text-text1">Risk Management</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                { label: 'Daily Loss Limit', value: '₹6,250 (25%)', desc: 'Allows 2 full SL hits before halt', icon: AlertCircle, color: 'red' },
                { label: 'Max Trades/Day', value: '3', desc: 'Maximum number of trades per session', icon: Layers, color: 'amber' },
                { label: 'Drawdown Halt', value: '20%', desc: 'Stop trading if drawdown from peak > 20%', icon: XCircle, color: 'red' },
              ].map(({ label, value, desc, icon: Icon, color }) => {
                const cardMap = {
                  red: { border: 'border-red/15', bg: 'bg-red/5', text: 'text-red' },
                  amber: { border: 'border-amber/15', bg: 'bg-amber/5', text: 'text-amber' },
                } as const
                const cm = cardMap[color as keyof typeof cardMap]
                return (
                <div key={label} className={clsx('rounded-xl border p-4', cm.border, cm.bg)}>
                  <div className="flex items-center gap-2 mb-2">
                    <Icon size={12} className={cm.text} />
                    <span className="text-[11px] font-bold text-text1">{label}</span>
                  </div>
                  <div className={clsx('text-xl font-extrabold font-mono', cm.text)}>{value}</div>
                  <div className="text-[10px] text-text3 mt-1">{desc}</div>
                </div>
              )})}
            </div>
          </motion.div>
        </div>

        {/* Right side - Quick start + Info */}
        <div className="space-y-4">

          {/* Quick Start Guide */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-green/10 flex items-center justify-center">
                <BookOpen size={13} className="text-green" />
              </div>
              <span className="text-[12px] font-bold text-text1">Quick Start</span>
            </div>
            <div className="space-y-3">
              {[
                { step: 1, label: 'Login to Kite', desc: 'Visit kite.zerodha.com', icon: Globe, status: status === 'ok' ? 'done' : 'pending' },
                { step: 2, label: 'Get Access Token', desc: 'From Kite Connect portal', icon: Key, status: status === 'ok' ? 'done' : 'pending' },
                { step: 3, label: 'Paste Token Above', desc: 'Or use Auto-Auth button', icon: Terminal, status: status === 'ok' ? 'done' : 'pending' },
                { step: 4, label: 'Bot Starts Trading', desc: 'During market hours 9:15–3:30', icon: Zap, status: 'pending' },
              ].map(({ step, label, desc, icon: Icon, status: s }) => (
                <motion.div key={step} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: step * 0.05 }}
                  className={clsx('flex items-start gap-3 p-2.5 rounded-xl transition-colors',
                    s === 'done' ? 'bg-green/5' : 'hover:bg-surface/50')}>
                  <div className={clsx('w-6 h-6 rounded-lg flex items-center justify-center shrink-0 text-[10px] font-bold',
                    s === 'done' ? 'bg-green/15 text-green' : 'bg-surface border border-line/30 text-text3')}>
                    {s === 'done' ? <CheckCircle2 size={12} /> : step}
                  </div>
                  <div>
                    <div className={clsx('text-[11px] font-bold', s === 'done' ? 'text-green' : 'text-text1')}>{label}</div>
                    <div className="text-[10px] text-text3">{desc}</div>
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>

          {/* System info */}
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
            className="glass-card rounded-2xl p-5 neon-border">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
                <Terminal size={13} className="text-accent" />
              </div>
              <span className="text-[12px] font-bold text-text1">System Info</span>
            </div>
            <div className="space-y-2">
              {[
                ['Bot Version', 'v2.0.0'],
                ['API', 'FastAPI + WebSocket'],
                ['Exchange', 'NSE / NFO'],
                ['Instrument', 'NIFTY Index Options'],
                ['Entry Order', 'Aggressive Limit'],
                ['SL Protection', 'SL-M (Exchange)'],
                ['Lot Size', '65 (1 lot)'],
                ['Capital', '₹25,000'],
                ['Risk/Trade', '2%'],
                ['Timezone', 'IST (Asia/Kolkata)'],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between items-center py-1 border-b border-line/10 last:border-0">
                  <span className="text-[11px] text-text3">{k}</span>
                  <span className="text-[11px] font-bold font-mono text-text2">{v}</span>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
