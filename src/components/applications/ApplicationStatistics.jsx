import { useMemo } from 'react'
import Card from '../ui/Card'
import StatCard from '../ui/StatCard'
import { applicationStatistics } from '../../modules/applications/applicationStatistics'

const today = () => new Date().toISOString().slice(0, 10)

function CountTable({ title, rows, empty }) {
  return (
    <Card title={title} className="!p-4">
      {rows.length === 0 ? (
        <p className="text-sm text-stone-500">{empty}</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-stone-100 last:border-0 dark:border-stone-800">
                <td className="py-1.5 pr-3 text-stone-700 dark:text-stone-300">{row.label}</td>
                <td className="py-1.5 text-right font-medium tabular-nums">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Counts and medians computed from the application store only; a missing fact is said, not guessed. */
export default function ApplicationStatistics({ store, settings }) {
  const stats = useMemo(() => applicationStatistics(store, settings, today()), [store, settings])
  if (stats.total === 0) {
    return <p className="text-sm text-stone-600 dark:text-stone-400">No applications in the tracker yet, so there is nothing to count.</p>
  }
  const maxWeek = Math.max(1, ...stats.perWeek.map((w) => w.count))
  const gaps = [
    stats.missing.appliedDate && `${plural(stats.missing.appliedDate, 'application')} without an applied date (left out of the weekly counts)`,
    stats.missing.channel && `${plural(stats.missing.channel, 'application')} without a channel`,
    stats.missing.cv && `${plural(stats.missing.cv, 'application')} without a recorded CV`,
    stats.missing.stageDates && `${plural(stats.missing.stageDates, 'time in stage')} could not be measured (no date)`,
  ].filter(Boolean)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Applications" value={stats.total} subtext="not counting voided ones" />
        <StatCard label="Still open" value={stats.open} />
        <StatCard label="Closed with an outcome" value={stats.total - stats.open} />
      </div>
      {gaps.length > 0 && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Not recorded: {gaps.join('; ')}.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <CountTable title="By stage" rows={stats.perStage} empty="No applications." />
        <CountTable title="By channel" rows={stats.perChannel} empty="No channel is recorded on any application." />
        <CountTable title="By CV used" rows={stats.perCv} empty="No CV is recorded on any application." />
        <CountTable title="Outcomes" rows={stats.outcomes} empty="No application has an outcome yet." />
        <Card title="Median days in stage" className="!p-4">
          <table className="w-full text-sm">
            <tbody>
              {stats.medianDaysInStage.map((row) => (
                <tr key={row.key} className="border-b border-stone-100 last:border-0 dark:border-stone-800">
                  <td className="py-1.5 pr-3 text-stone-700 dark:text-stone-300">{row.label}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    <span className="font-medium">{row.median}</span>
                    <span className="ml-1 text-xs text-stone-500">({plural(row.spells, 'spell')})</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-stone-500">Spells still running count up to today.</p>
        </Card>
        <Card title="Applications per week" className="!p-4">
          {stats.perWeek.length === 0 ? (
            <p className="text-sm text-stone-500">No application has an applied date.</p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
              {stats.perWeek.map((w) => (
                <li key={w.week} className="flex items-center gap-2">
                  <span className="w-20 shrink-0 tabular-nums text-stone-500">{w.week}</span>
                  <span className="h-2 rounded bg-teal-500" style={{ width: `${(w.count / maxWeek) * 100}%`, minWidth: w.count ? 4 : 0 }} />
                  <span className="tabular-nums">{w.count}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-stone-500">Weeks start on Monday.</p>
        </Card>
      </div>
    </div>
  )
}
