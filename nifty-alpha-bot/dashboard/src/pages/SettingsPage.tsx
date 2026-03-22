import React, { useEffect, useState } from 'react'
import axios from 'axios'
import { Save, CheckCircle2, Key, Sliders, BookOpen, Loader2 } from 'lucide-react'
import clsx from 'clsx'

export function SettingsPage() {
  const [config, setConfig]   = useState<any>(null)
  const [token,  setToken]    = useState('')
  const [saved,  setSaved]    = useState(false)
  const [show,   setShow]     = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/strategy/config')
      .then(r => { setConfig(r.data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const save = async () => {
    if (!token.trim()) return
    await axios.post('/api/kite/token', { access_token: token })
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  const STEPS = [
    { n:'1', title:'Setup credentials',   body:<>Copy <code className="font-mono text-accent text-xs">.env.example</code> → <code className="font-mono text-accent text-xs">.env</code> and fill in your Kite API key & secret</> },
    { n:'2', title:'Verify edge',         body:<>Run <code className="font-mono text-accent text-xs">python -m backtest.daily_backtest --walk-forward</code> and confirm all 3 periods are profitable</> },
    { n:'3', title:'Paper trade',         body:<>Run <code className="font-mono text-accent text-xs">python -m bot.main --paper</code> for at least 1 week before going live</> },
    { n:'4', title:'Set token daily',     body:'Paste your Kite access token above every morning before 9:15 AM' },
    { n:'5', title:'Go live',             body:<>Run <code className="font-mono text-accent text-xs">python -m bot.main</code> — monitor via this dashboard</> },
  ]

  return (
    <div className="p-4 lg:p-5 space-y-4 max-w-2xl mx-auto">
      <h1 className="text-lg font-bold text-text1 tracking-tight">Settings</h1>

      {/* Token card */}
      <div className="bg-card rounded-xl border border-line p-5">
        <div className="flex items-start gap-3 mb-5">
          <div className="p-2 rounded-lg bg-accentDim shrink-0">
            <Key size={15} className="text-accent" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-text1">Kite Access Token</h2>
            <p className="text-xs text-text3 mt-0.5">
              Zerodha generates a new token every day. Paste it here before 9:15 AM.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input
              type={show ? 'text' : 'password'}
              placeholder="Paste access_token here..."
              value={token}
              onChange={e => setToken(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && save()}
              className="w-full bg-bg border border-line rounded-lg px-3 py-2.5 text-sm text-text1 font-mono pr-14 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
            <button
              onClick={() => setShow(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-bold text-text3 hover:text-text2 transition-colors"
            >
              {show ? 'HIDE' : 'SHOW'}
            </button>
          </div>
          <button
            onClick={save}
            disabled={!token.trim()}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-all whitespace-nowrap',
              saved
                ? 'bg-greenDim border-green/30 text-green'
                : 'bg-accent border-accent text-white hover:bg-sky disabled:opacity-40 disabled:cursor-not-allowed'
            )}
          >
            {saved ? <CheckCircle2 size={14}/> : <Save size={14}/>}
            {saved ? 'Saved!' : 'Save'}
          </button>
        </div>
      </div>

      {/* Strategy config */}
      <div className="bg-card rounded-xl border border-line p-5">
        <div className="flex items-start gap-3 mb-5">
          <div className="p-2 rounded-lg bg-accentDim shrink-0">
            <Sliders size={15} className="text-accent" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-text1">Strategy Parameters</h2>
            <p className="text-xs text-text3 mt-0.5">Read-only. Edit <code className="font-mono text-accent text-xs">.env</code> to change values.</p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-text3 py-2">
            <Loader2 size={13} className="animate-spin"/> Loading...
          </div>
        ) : config ? (
          <div className="divide-y divide-line/40">
            {Object.entries(config).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between py-2.5 gap-4">
                <span className="text-xs text-text2 font-medium">{key.replace(/_/g, ' ')}</span>
                <span className={clsx(
                  'font-mono text-xs font-semibold',
                  typeof value === 'boolean'
                    ? value ? 'text-green' : 'text-red'
                    : 'text-text1'
                )}>
                  {String(value)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-text3">Could not load strategy config. Is the API running?</p>
        )}
      </div>

      {/* Quick start */}
      <div className="bg-card rounded-xl border border-line p-5">
        <div className="flex items-start gap-3 mb-5">
          <div className="p-2 rounded-lg bg-accentDim shrink-0">
            <BookOpen size={15} className="text-accent" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-text1">Quick Start Guide</h2>
            <p className="text-xs text-text3 mt-0.5">Follow these steps to start live trading safely.</p>
          </div>
        </div>
        <ol className="space-y-4">
          {STEPS.map(({ n, title, body }) => (
            <li key={n} className="flex gap-4">
              <span className="w-7 h-7 shrink-0 rounded-full bg-accentDim border border-accent/20 flex items-center justify-center text-xs font-bold text-accent">
                {n}
              </span>
              <div className="pt-0.5">
                <p className="text-sm font-semibold text-text1 mb-0.5">{title}</p>
                <p className="text-xs text-text3 leading-relaxed">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
