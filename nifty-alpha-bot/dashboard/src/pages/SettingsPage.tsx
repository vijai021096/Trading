import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import clsx from 'clsx'
import axios from 'axios'
import {
  Settings, Key, Shield, CheckCircle2, XCircle, AlertCircle, Copy, Eye, EyeOff,
  RefreshCw, Loader2, BookOpen, Terminal, Globe, Lock, Zap, Clock, BarChart3,
  ChevronRight, Layers, SlidersHorizontal,   Radio, Radar
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
    <div className="flex-1 overflow-y-auto">
      {/* ── Gradient hero header ────────────────────────────── */}
      <div className="relative overflow-hidden bg-gradient-to-br from-slate-900/60 via-bg to-accent/5 border-b border-line/20 px-4 lg:px-6 py-5">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 left-0 w-72 h-32 bg-accent/4 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4" />
        </div>
        <div className="relative flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-slate-600 to-accent/70 flex items-center justify-center shadow-lg">
            <Settings size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-black text-text1 tracking-tight">Settings</h1>
            <p className="text-[11px] text-text3 mt-0.5">Authentication · strategy parameters · system config</p>
          </div>
        </div>
      </div>
      <div className="px-4 lg:px-6 py-5 max-w-[1640px] mx-auto space-y-4">

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

          <TradingEnginePanel />

          {/* Strategy Parameters — from API */}
          <StrategyParamsPanel />

          {/* Risk Management — from API */}
          <RiskParamsPanel />
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

          {/* System info — from API */}
          <SystemInfoPanel />
        </div>
      </div>
      </div>
    </div>
  )
}

/* ── Trading engine (live from API / .env) ───────────────── */
function TradingEnginePanel() {
  const [cfg, setCfg] = useState<any>(null)
  useEffect(() => { axios.get('/api/strategy/config').then(r => setCfg(r.data)).catch(() => {}) }, [])

  if (!cfg) return null
  const eng = String(cfg.trading_engine || 'intraday')
  const isDaily = eng.toLowerCase() === 'daily_adaptive'

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
      className={clsx(
        'glass-card rounded-2xl p-5 neon-border border-l-[3px]',
        isDaily ? 'border-l-cyan' : 'border-l-amber',
      )}>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
            <Radar size={13} className="text-cyan" />
          </div>
          <span className="text-[12px] font-bold text-text1">Trading engine</span>
        </div>
        <span className={clsx(
          'text-[10px] font-black uppercase tracking-widest px-3 py-1 rounded-lg border',
          isDaily ? 'bg-cyan/10 border-cyan/25 text-cyan' : 'bg-amber/10 border-amber/25 text-amber',
        )}>
          {eng.replace(/_/g, ' ')}
        </span>
      </div>
      <p className="text-[11px] text-text3 leading-relaxed mb-4">
        {isDaily ? (
          <>
            <span className="text-text2 font-semibold">Daily adaptive</span> matches the daily backtest stack (regime + 7 strategies + adaptive scan order).
            Live entries use the last <strong>completed</strong> daily candle and today&apos;s VIX; size uses anchor month + DD tiers (see <code className="text-accent">Watch</code> tab).
          </>
        ) : (
          <>
            <span className="text-text2 font-semibold">Intraday</span> uses 5m ORB / VWAP / EMA / momentum with trend + daily regime filters.
          </>
        )}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
        {[
          { k: 'Strategy filter', v: cfg.daily_strategy_filter ?? '—', hint: 'DAILY_STRATEGY_FILTER' },
          { k: 'Entry window', v: `${cfg.daily_adaptive_window_start || '—'} – ${cfg.daily_adaptive_window_end || '—'}`, hint: 'IST' },
          { k: 'Nifty opt lot', v: String(cfg.nifty_option_lot_size ?? '—'), hint: 'units / lot' },
          { k: 'Base lots', v: String(cfg.daily_base_lots ?? '—'), hint: 'DAILY_BASE_LOTS' },
        ].map(({ k, v, hint }) => (
          <div key={k} className="rounded-xl border border-line/15 bg-surface/35 p-3">
            <div className="text-[9px] font-bold text-text3 uppercase">{k}</div>
            <div className="text-[13px] font-mono font-bold text-text1 mt-0.5">{v}</div>
            <div className="text-[9px] text-text3 mt-1 font-mono">{hint}</div>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-text3 mt-3">
        Set <code className="text-amber">TRADING_ENGINE=daily_adaptive</code> or <code className="text-amber">intraday</code> in <code>.env</code> and restart the bot + API.
      </p>
    </motion.div>
  )
}

/* ── Strategy Params (live from API) ─────────────────────── */
function StrategyParamsPanel() {
  const [cfg, setCfg] = useState<any>(null)
  useEffect(() => { axios.get('/api/strategy/config').then(r => setCfg(r.data)).catch(() => {}) }, [])

  if (!cfg) return null
  const slTarget = cfg.sl_target_by_strategy || {}
  const backtest = cfg.backtest_stats || {}

  const STRAT_ICONS: Record<string, { icon: any; color: string }> = {
    ORB:               { icon: Zap,   color: 'text-amber' },
    RELAXED_ORB:       { icon: Zap,   color: 'text-amber' },
    EMA_PULLBACK:      { icon: BarChart3, color: 'text-accent' },
    VWAP_RECLAIM:      { icon: BarChart3, color: 'text-cyan' },
    MOMENTUM_BREAKOUT: { icon: Zap,   color: 'text-green' },
  }

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
      className="glass-card rounded-2xl p-5 neon-border">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-lg bg-cyan/10 flex items-center justify-center">
          <SlidersHorizontal size={13} className="text-cyan" />
        </div>
        <span className="text-[12px] font-bold text-text1">Strategy Parameters</span>
        <span className="text-[9px] font-bold text-text3 bg-surface px-2 py-0.5 rounded-lg border border-line/20 uppercase tracking-wider">Live Config</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {Object.entries(slTarget).map(([name, params]: [string, any]) => {
          const meta = STRAT_ICONS[name] || { icon: Zap, color: 'text-text2' }
          const Icon = meta.icon
          const bs = backtest[name] || {}
          return (
            <div key={name} className="rounded-xl border border-line/20 p-3.5 bg-surface/30">
              <div className="flex items-center gap-2 mb-3">
                <div className={clsx('w-5 h-5 rounded flex items-center justify-center', `bg-${meta.color.replace('text-', '')}/10`)}>
                  <Icon size={10} className={meta.color} />
                </div>
                <span className="text-[11px] font-bold text-text1">{name.replace(/_/g, ' ')}</span>
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-text3">Stop Loss</span>
                  <span className="text-[11px] font-bold font-mono text-red">{(params.sl_pct * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-text3">Target</span>
                  <span className="text-[11px] font-bold font-mono text-green">{(params.target_pct * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-text3">R:R</span>
                  <span className="text-[11px] font-bold font-mono text-accent">{(params.target_pct / params.sl_pct).toFixed(1)}x</span>
                </div>
                {bs.win_rate > 0 && (
                  <>
                    <div className="border-t border-line/10 pt-1.5 mt-1.5" />
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] text-text3">BT Win Rate</span>
                      <span className={clsx('text-[11px] font-bold font-mono', bs.win_rate >= 0.5 ? 'text-green' : 'text-amber')}>{(bs.win_rate * 100).toFixed(0)}%</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] text-text3">BT Profit Factor</span>
                      <span className={clsx('text-[11px] font-bold font-mono', bs.profit_factor >= 2 ? 'text-green' : 'text-amber')}>{bs.profit_factor.toFixed(2)}</span>
                    </div>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Time windows */}
      <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {[
          { label: 'ORB Window', val: `${cfg.orb_start} – ${cfg.orb_end}` },
          { label: 'Entry Close', val: cfg.entry_window_close },
          { label: 'EMA Pullback', val: `${cfg.ema_pullback_window_start || '09:30'} – ${cfg.ema_pullback_window_end || '13:00'}` },
          { label: 'Momentum', val: `${cfg.momentum_breakout_window_start || '09:30'} – ${cfg.momentum_breakout_window_end || '12:00'}` },
          { label: 'VWAP Window', val: `${cfg.reclaim_window_start} – ${cfg.reclaim_window_end}` },
          { label: 'Trail Trigger', val: `${(cfg.trail_trigger_pct * 100).toFixed(0)}%` },
        ].map(({ label, val }) => (
          <div key={label} className="bg-surface/40 rounded-lg p-2.5 border border-line/15">
            <div className="text-[9px] font-bold text-text3 uppercase mb-1">{label}</div>
            <div className="text-[11px] font-bold font-mono text-text1">{val}</div>
          </div>
        ))}
      </div>
    </motion.div>
  )
}

/* ── Risk Params (live from API) ──────────────────────────── */
function RiskParamsPanel() {
  const [cfg, setCfg] = useState<any>(null)
  useEffect(() => { axios.get('/api/strategy/config').then(r => setCfg(r.data)).catch(() => {}) }, [])

  if (!cfg) return null

  const riskItems = [
    { label: 'Daily Loss Limit', value: `${(cfg.max_daily_loss_pct * 100).toFixed(0)}% (₹${Math.round(cfg.capital * cfg.max_daily_loss_pct).toLocaleString('en-IN')})`, desc: 'Soft stop on daily P&L', icon: AlertCircle, color: 'red' },
    { label: 'Hard Daily Limit', value: `₹${cfg.max_daily_loss_hard?.toLocaleString('en-IN') ?? '--'}`, desc: 'Absolute max daily loss', icon: XCircle, color: 'red' },
    { label: 'Max Trades/Day', value: `${cfg.max_trades_per_day}`, desc: 'Maximum entries per session', icon: Layers, color: 'amber' },
    { label: 'Drawdown Halt', value: `${(cfg.max_drawdown_pct ?? 20)}%`, desc: 'Stop if drawdown > this', icon: XCircle, color: 'red' },
    { label: 'Risk per Trade', value: `${(cfg.risk_per_trade_pct * 100).toFixed(1)}%`, desc: `₹${Math.round(cfg.capital * cfg.risk_per_trade_pct).toLocaleString('en-IN')} max risk`, icon: Shield, color: 'amber' },
    { label: 'Break-Even', value: `${(cfg.break_even_trigger_pct * 100).toFixed(0)}%`, desc: 'Move SL to entry after', icon: Lock, color: 'amber' },
  ]

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
      className="glass-card rounded-2xl p-5 neon-border">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-lg bg-red/10 flex items-center justify-center">
          <Shield size={13} className="text-red" />
        </div>
        <span className="text-[12px] font-bold text-text1">Risk Management</span>
        <span className="text-[9px] font-bold text-text3 bg-surface px-2 py-0.5 rounded-lg border border-line/20 uppercase tracking-wider">Live Config</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {riskItems.map(({ label, value, desc, icon: Icon, color }) => {
          const cm = color === 'red'
            ? { border: 'border-red/15', bg: 'bg-red/5', text: 'text-red' }
            : { border: 'border-amber/15', bg: 'bg-amber/5', text: 'text-amber' }
          return (
            <div key={label} className={clsx('rounded-xl border p-3.5', cm.border, cm.bg)}>
              <div className="flex items-center gap-2 mb-2">
                <Icon size={12} className={cm.text} />
                <span className="text-[11px] font-bold text-text1">{label}</span>
              </div>
              <div className={clsx('text-lg font-extrabold font-mono', cm.text)}>{value}</div>
              <div className="text-[10px] text-text3 mt-1">{desc}</div>
            </div>
          )
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="bg-surface/40 rounded-lg p-2.5 border border-line/15">
          <div className="text-[9px] font-bold text-text3 uppercase mb-1">Entry Orders</div>
          <div className="text-[11px] font-bold text-text1">{cfg.use_limit_orders ? `Aggressive Limit (+${(cfg.limit_price_buffer_pct * 100).toFixed(1)}%)` : 'Market'}</div>
        </div>
        <div className="bg-surface/40 rounded-lg p-2.5 border border-line/15">
          <div className="text-[9px] font-bold text-text3 uppercase mb-1">SL Protection</div>
          <div className="text-[11px] font-bold text-text1">{cfg.use_slm_exit ? 'SL-M (Exchange)' : 'Software SL'}</div>
        </div>
      </div>
    </motion.div>
  )
}

/* ── System Info (live from API) ──────────────────────────── */
function SystemInfoPanel() {
  const [cfg, setCfg] = useState<any>(null)
  useEffect(() => { axios.get('/api/strategy/config').then(r => setCfg(r.data)).catch(() => {}) }, [])

  const items = cfg ? [
    ['Bot Version', cfg.bot_version ?? 'v3.1.0'],
    ['Trading engine', String(cfg.trading_engine || '—').replace(/_/g, ' ')],
    ['API', 'FastAPI + WebSocket'],
    ['Exchange', 'NSE / NFO'],
    ['Instrument', 'NIFTY Index Options'],
    ['Entry Order', cfg.use_limit_orders ? 'Aggressive Limit' : 'Market'],
    ['SL Protection', cfg.use_slm_exit ? 'SL-M (Exchange)' : 'Software SL'],
    ['Lot Size', `${cfg.lot_size} (1 lot)`],
    ['Capital', `₹${cfg.capital?.toLocaleString('en-IN')}`],
    ['Risk/Trade', `${(cfg.risk_per_trade_pct * 100).toFixed(1)}%`],
    ['Mode', cfg.paper_mode ? 'PAPER (Simulated)' : 'LIVE'],
    ['Timezone', 'IST (Asia/Kolkata)'],
  ] : [
    ['Status', 'Loading...'],
  ]

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
      className="glass-card rounded-2xl p-5 neon-border">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
          <Terminal size={13} className="text-accent" />
        </div>
        <span className="text-[12px] font-bold text-text1">System Info</span>
      </div>
      <div className="space-y-2">
        {items.map(([k, v]) => (
          <div key={k} className="flex justify-between items-center py-1 border-b border-line/10 last:border-0">
            <span className="text-[11px] text-text3">{k}</span>
            <span className={clsx('text-[11px] font-bold font-mono',
              k === 'Mode' && v === 'LIVE' ? 'text-green' : k === 'Mode' ? 'text-amber' : 'text-text2')}>{v}</span>
          </div>
        ))}
      </div>
    </motion.div>
  )
}
