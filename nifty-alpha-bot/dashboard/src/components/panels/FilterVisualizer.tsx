import { motion } from 'framer-motion'
import { CheckCircle2, XCircle, Clock, Filter } from 'lucide-react'
import clsx from 'clsx'

interface Props {
  filterLog: Record<string, any>
  compact?: boolean
}

export function FilterVisualizer({ filterLog, compact = false }: Props) {
  const entries = Object.entries(filterLog || {})
  if (!entries.length) return null

  const passed = entries.filter(([, v]) => v === true || v?.passed).length
  const total  = entries.length
  const pct    = total > 0 ? (passed / total * 100) : 0
  const allPass = passed === total

  if (compact) {
    return (
      <div className="flex items-center gap-1.5">
        <div className="flex items-center gap-1">
          {entries.slice(0, 6).map(([key, v], i) => {
            const ok = v === true || v?.passed
            return <div key={i} className={clsx('w-1.5 h-4 rounded-full', ok ? 'bg-green' : 'bg-red/60')} />
          })}
        </div>
        <span className={clsx('text-[10px] font-bold', allPass ? 'text-green' : 'text-text3')}>
          {passed}/{total}
        </span>
      </div>
    )
  }

  return (
    <div className="glass-card rounded-2xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-accent/10 flex items-center justify-center">
            <Filter size={13} className="text-accent" />
          </div>
          <span className="text-[11px] font-bold tracking-[0.15em] uppercase text-text3">Entry Filters</span>
        </div>
        <div className={clsx('flex items-center gap-1.5 px-2 py-0.5 rounded-lg text-[10px] font-bold',
          allPass ? 'bg-green/10 text-green' : 'bg-amber/10 text-amber')}>
          {allPass ? <CheckCircle2 size={10} /> : <Clock size={10} />}
          {passed}/{total} passed
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-surface overflow-hidden mb-4">
        <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }}
          className={clsx('h-full rounded-full', allPass ? 'bg-green' : 'bg-amber')} />
      </div>

      {/* Filters grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {entries.map(([key, v], i) => {
          const ok = v === true || v?.passed
          return (
            <motion.div key={key} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.03 }}
              className={clsx('flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-[11px] font-medium',
                ok ? 'bg-green/5 border-green/15 text-green' : 'bg-red/5 border-red/15 text-red-l/70')}>
              {ok ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
              <span className="truncate capitalize">{key.replace(/_/g, ' ')}</span>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
