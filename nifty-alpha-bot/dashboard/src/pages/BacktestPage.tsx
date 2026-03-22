import React, { useState } from 'react'
import axios from 'axios'
import clsx from 'clsx'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'
import { Play, Loader2, CheckCircle2, XCircle, TrendingUp, BarChart2, ShieldAlert, Zap, Award } from 'lucide-react'

export function BacktestPage() {
  const [months,  setMonths]  = useState(6)
  const [capital, setCapital] = useState(100000)
  const [running, setRunning] = useState(false)
  const [result,  setResult]  = useState<any>(null)
  const [error,   setError]   = useState('')

  const run = async () => {
    setRunning(true); setError('')
    try {
      const r = await axios.post('/api/backtest/run', { months, capital })
      setResult(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Backtest failed')
    } finally {
      setRunning(false)
    }
  }

  const m   = result?.metrics
  const eq  = (m?.equity_curve ?? []).map((v: number, i: number) => ({ i, equity: v }))
  const good = m && m.sharpe_ratio >= 1 && m.max_drawdown_pct <= 15 && m.total_net_pnl > 0

  return (
    <div className="p-4 lg:p-5 space-y-4 max-w-screen-xl mx-auto">

      <h1 className="text-lg font-bold text-text1 tracking-tight">Strategy Backtest</h1>

      {/* Config card */}
      <div className="bg-card rounded-xl border border-line p-5">
        <p className="text-[11px] font-semibold tracking-widest uppercase text-text3 mb-4">Configuration</p>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Data range (months)">
            <input
              type="number" value={months} min={1} max={12}
              onChange={e => setMonths(+e.target.value)}
              className="w-32 bg-bg border border-line rounded-lg px-3 py-2 text-sm text-text1 font-mono focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </Field>
          <Field label="Capital (₹)">
            <input
              type="number" value={capital} step={10000}
              onChange={e => setCapital(+e.target.value)}
              className="w-40 bg-bg border border-line rounded-lg px-3 py-2 text-sm text-text1 font-mono focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
          </Field>
          <button
            onClick={run} disabled={running}
            className="flex items-center gap-2 h-9 px-6 bg-accent hover:bg-sky disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? 'Running...' : 'Run Backtest'}
          </button>
        </div>

        {running && (
          <div className="mt-3 flex items-center gap-2 text-sm text-accent">
            <Loader2 size={13} className="animate-spin shrink-0" />
            Downloading data & simulating trades — this takes 30–60 seconds
          </div>
        )}
        {error && (
          <div className="mt-3 flex items-center gap-2 text-sm text-red bg-redDim rounded-lg px-3 py-2.5 border border-red/20">
            <XCircle size={14} className="shrink-0" /> {error}
          </div>
        )}
      </div>

      {!m && !running && (
        <div className="flex flex-col items-center justify-center py-20 text-text3">
          <BarChart2 size={44} strokeWidth={1} className="mb-4 opacity-30" />
          <p className="text-sm font-medium text-text2">Run a backtest to see results</p>
          <p className="text-xs mt-1">Data is fetched from Yahoo Finance (yfinance)</p>
        </div>
      )}

      {m && (
        <>
          {/* Verdict */}
          <div className={clsx(
            'flex items-start gap-3 rounded-xl border p-4',
            good ? 'bg-greenDim border-green/30' : 'bg-amberDim border-amber/30'
          )}>
            {good
              ? <CheckCircle2 size={18} className="text-green mt-0.5 shrink-0" />
              : <ShieldAlert  size={18} className="text-amber mt-0.5 shrink-0" />}
            <div>
              <p className={clsx('font-bold text-sm mb-1', good ? 'text-green' : 'text-amber')}>
                {good ? 'Strategy passes all criteria' : 'Strategy needs improvement'}
              </p>
              <p className="text-xs text-text2">
                Sharpe {m.sharpe_ratio?.toFixed(2)} {m.sharpe_ratio >= 1 ? '✓' : '✗ (need ≥1.0)'}
                &ensp;·&ensp;Max DD {m.max_drawdown_pct?.toFixed(1)}% {m.max_drawdown_pct <= 15 ? '✓' : '✗ (need ≤15%)'}
                &ensp;·&ensp;P&L {m.total_net_pnl >= 0 ? '+' : ''}₹{m.total_net_pnl?.toLocaleString('en-IN', {maximumFractionDigits:0})} {m.total_net_pnl > 0 ? '✓' : '✗'}
              </p>
            </div>
          </div>

          {/* Key metrics */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {([
              { label:'Net P&L',       val:`${m.total_net_pnl>=0?'+':''}₹${Math.abs(m.total_net_pnl??0).toLocaleString('en-IN',{maximumFractionDigits:0})}`, good:m.total_net_pnl>=0, icon:TrendingUp },
              { label:'Return',        val:`${m.return_pct>=0?'+':''}${m.return_pct?.toFixed(1)}%`, good:m.return_pct>=0, icon:TrendingUp },
              { label:'Win Rate',      val:`${m.win_rate_pct?.toFixed(1)}%`, good:m.win_rate_pct>=45, icon:Award },
              { label:'Max Drawdown',  val:`${m.max_drawdown_pct?.toFixed(1)}%`, good:m.max_drawdown_pct<=15, icon:ShieldAlert },
              { label:'Sharpe',        val:m.sharpe_ratio?.toFixed(2), good:m.sharpe_ratio>=1, icon:BarChart2 },
              { label:'Profit Factor', val:m.profit_factor?.toFixed(2), good:m.profit_factor>=1.5, icon:Zap },
            ] as any[]).map(({ label, val, good: g, icon: Icon }) => (
              <div key={label} className={clsx(
                'bg-card rounded-xl border border-l-2 p-4',
                g ? 'border-line border-l-green' : 'border-line border-l-red'
              )}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold tracking-widest uppercase text-text3">{label}</span>
                  <Icon size={12} className={g ? 'text-green' : 'text-red'} />
                </div>
                <div className={clsx('font-mono text-xl font-bold', g ? 'text-green' : 'text-red')}>{val}</div>
              </div>
            ))}
          </div>

          {/* Stats sub-row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {([
              { label:'Total Trades', val:String(m.total_trades??0) },
              { label:'Avg Win',      val:`₹${(m.avg_win??0).toLocaleString('en-IN',{maximumFractionDigits:0})}` },
              { label:'Avg Loss',     val:`₹${Math.abs(m.avg_loss??0).toLocaleString('en-IN',{maximumFractionDigits:0})}` },
              { label:'Total Charges',val:`₹${(m.total_charges??0).toLocaleString('en-IN',{maximumFractionDigits:0})}` },
            ] as any[]).map(({ label, val }) => (
              <div key={label} className="bg-card rounded-xl border border-line p-4">
                <div className="text-[11px] font-semibold tracking-widest uppercase text-text3 mb-2">{label}</div>
                <div className="font-mono text-lg font-semibold text-text1">{val}</div>
              </div>
            ))}
          </div>

          {/* Equity curve */}
          {eq.length > 0 && (
            <div className="bg-card rounded-xl border border-line p-5">
              <div className="flex items-center justify-between mb-5">
                <span className="text-sm font-semibold text-text1">Equity Curve</span>
                <span className="font-mono text-xs text-text3">{eq.length} data points</span>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={eq} margin={{ top:4, right:4, bottom:0, left:0 }}>
                    <defs>
                      <linearGradient id="eqG" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#5b7bf7" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="#5b7bf7" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#252d45" vertical={false}/>
                    <XAxis dataKey="i" tick={{ fill:'#4b5473', fontSize:10, fontFamily:'JetBrains Mono' }} tickLine={false} axisLine={false}/>
                    <YAxis tick={{ fill:'#4b5473', fontSize:10, fontFamily:'JetBrains Mono' }} tickLine={false} axisLine={false} width={56} tickFormatter={v=>`₹${(v/1000).toFixed(0)}k`}/>
                    <ReferenceLine y={capital} stroke="#252d45" strokeDasharray="4 4"/>
                    <Tooltip
                      contentStyle={{ background:'#0f1221', border:'1px solid #252d45', borderRadius:8, fontSize:12 }}
                      labelStyle={{ color:'#9ba3bf' }}
                      formatter={(v:any) => [`₹${Number(v).toLocaleString('en-IN')}`, 'Capital']}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#5b7bf7" fill="url(#eqG)" strokeWidth={2} dot={false} activeDot={{ r:4, fill:'#5b7bf7' }}/>
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Monthly table */}
          {m.monthly_breakdown?.length > 0 && (
            <div className="bg-card rounded-xl border border-line overflow-hidden">
              <div className="px-5 py-3 border-b border-line">
                <span className="text-sm font-semibold text-text1">Monthly Breakdown</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-line">
                      {['Month','Trades','Win Rate','Net P&L','Charges'].map(h => (
                        <th key={h} className="py-3 px-5 text-left text-[11px] font-semibold tracking-wider uppercase text-text3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {m.monthly_breakdown.map((mo: any, i: number) => (
                      <tr key={mo.month} className={clsx('border-b border-line/40 hover:bg-cardHigh transition-colors', i%2===1&&'bg-bg/30')}>
                        <td className="py-3 px-5 font-mono text-sm text-text2 font-medium">{mo.month}</td>
                        <td className="py-3 px-5 font-mono text-sm text-text1">{mo.trades}</td>
                        <td className="py-3 px-5">
                          <span className={clsx('font-mono text-sm font-semibold', mo.win_rate >= 50 ? 'text-green' : 'text-text2')}>
                            {mo.win_rate}%
                          </span>
                        </td>
                        <td className={clsx('py-3 px-5 font-mono text-sm font-bold', (mo.net_pnl??0)>=0?'text-green':'text-red')}>
                          {(mo.net_pnl??0)>=0?'+':''}₹{Math.abs(mo.net_pnl??0).toLocaleString('en-IN')}
                        </td>
                        <td className="py-3 px-5 font-mono text-sm text-text3">₹{(mo.charges??0).toLocaleString('en-IN')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Exit reasons */}
          {m.exit_reasons && Object.keys(m.exit_reasons).length > 0 && (
            <div className="bg-card rounded-xl border border-line p-5">
              <p className="text-[11px] font-semibold tracking-widest uppercase text-text3 mb-4">Exit Breakdown</p>
              <div className="flex flex-wrap gap-3">
                {Object.entries(m.exit_reasons).map(([reason, count]) => (
                  <div key={reason} className={clsx(
                    'flex items-center gap-3 px-4 py-2.5 rounded-lg border',
                    reason === 'TARGET_HIT' ? 'bg-greenDim border-green/25' :
                    reason === 'SL_HIT'     ? 'bg-redDim border-red/25' :
                                              'bg-amberDim border-amber/25'
                  )}>
                    <span className={clsx('text-xs font-bold',
                      reason === 'TARGET_HIT' ? 'text-green' :
                      reason === 'SL_HIT'     ? 'text-red' : 'text-amber'
                    )}>{reason.replace(/_/g,' ')}</span>
                    <span className="font-mono text-base font-black text-text1">{String(count)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-text2">{label}</span>
      {children}
    </label>
  )
}
