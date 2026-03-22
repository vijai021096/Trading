import React from 'react'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Target, ShieldCheck, BarChart3, Layers } from 'lucide-react'
import { useTradingStore } from '../../stores/tradingStore'

export function LivePnLPanel() {
  const { position, dailyPnl } = useTradingStore()
  const pnl      = dailyPnl?.net_pnl ?? 0
  const isActive = position.state === 'ACTIVE'
  const hasTrade = isActive || position.state === 'ENTRY_PENDING'

  return (
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">

      <Card
        label="Today's P&L"
        value={`${pnl >= 0 ? '+' : ''}₹${Math.abs(pnl).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
        sub={`${dailyPnl?.trades ?? 0} trades  ·  ${(dailyPnl?.win_rate ?? 0).toFixed(0)}% win rate`}
        color={pnl >= 0 ? 'green' : 'red'}
        Icon={pnl >= 0 ? TrendingUp : TrendingDown}
        big
      />

      <Card
        label="Position"
        value={hasTrade ? position.state : 'IDLE'}
        sub={hasTrade ? `${position.direction} · ${position.symbol?.slice(-8) ?? ''}` : 'No open trade'}
        color={isActive ? 'accent' : 'dim'}
        Icon={Target}
        pulse={isActive}
      />

      {isActive ? (
        <Card
          label="SL → Target"
          value={`₹${position.current_sl?.toFixed(0) ?? '--'} → ₹${position.target_price?.toFixed(0) ?? '--'}`}
          sub={position.break_even_set ? '✓ Break-even locked' : 'Watching...'}
          color={position.break_even_set ? 'green' : 'dim'}
          Icon={ShieldCheck}
          mono
        />
      ) : (
        <Card
          label="Win / Loss"
          value={`${dailyPnl?.wins ?? 0}W  /  ${dailyPnl?.losses ?? 0}L`}
          sub={`${(dailyPnl?.win_rate ?? 0).toFixed(0)}% win rate today`}
          color={(dailyPnl?.win_rate ?? 0) >= 50 ? 'green' : 'dim'}
          Icon={BarChart3}
        />
      )}

      <Card
        label={isActive ? 'Strategy' : 'Trades Today'}
        value={isActive ? (position.strategy ?? '--') : `${dailyPnl?.trades ?? 0} / 3`}
        sub={isActive
          ? `Entry ₹${position.entry_price?.toFixed(0) ?? '--'}`
          : 'Max 3 per day'}
        color="dim"
        Icon={Layers}
      />
    </div>
  )
}

type Color = 'green' | 'red' | 'accent' | 'dim'

const colorMap: Record<Color, { border: string; icon: string; value: string; bg: string }> = {
  green:  { border: 'border-l-green',  icon: 'text-green',  value: 'text-green',  bg: 'bg-greenDim' },
  red:    { border: 'border-l-red',    icon: 'text-red',    value: 'text-red',    bg: 'bg-redDim' },
  accent: { border: 'border-l-accent', icon: 'text-accent', value: 'text-accent', bg: 'bg-accentDim' },
  dim:    { border: 'border-l-line',   icon: 'text-text3',  value: 'text-text1',  bg: 'bg-bg' },
}

function Card({
  label, value, sub, color, Icon, big, pulse, mono,
}: {
  label: string
  value: string
  sub: string
  color: Color
  Icon: React.ComponentType<any>
  big?: boolean
  pulse?: boolean
  mono?: boolean
}) {
  const c = colorMap[color]
  return (
    <div className={clsx(
      'bg-card rounded-xl border border-line border-l-2 p-4',
      c.border,
      pulse && 'animate-pulse-slow',
    )}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold tracking-widest uppercase text-text3">{label}</span>
        <div className={clsx('p-1.5 rounded-md', c.bg)}>
          <Icon size={13} className={c.icon} />
        </div>
      </div>
      <div className={clsx(
        'font-bold leading-tight mb-1',
        mono ? 'font-mono' : '',
        big ? 'text-2xl' : 'text-xl',
        c.value,
      )}>
        {value}
      </div>
      <div className="text-xs text-text3 truncate">{sub}</div>
    </div>
  )
}
