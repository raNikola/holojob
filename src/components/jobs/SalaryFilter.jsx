import { useEffect, useId, useState } from 'react'
import { X } from 'lucide-react'
import InfoTip from '../ui/InfoTip'
import { FILTER_HELP } from '../../modules/jobs/filterHelp'
import { SALARY_CLEARED, SALARY_RESET } from '../../modules/jobs/jobFilters'
import {
  RANGE_ERROR_TEXT,
  SALARY_PRESETS,
  describeRange,
  formatAmount,
  parseAmount,
  profileSalaryNote,
  rangeError,
  salaryMarker,
  sanitizeAmount,
} from '../../modules/jobs/salaryFilter'

/**
 * One control for the salary range in EUR per month. The typed text is a draft; the filter changes
 * only while From is not above To, so the last valid range stays active during an error.
 */
export default function SalaryFilter({ from, to, includeUnknown, filters, profile, onChange, className = '' }) {
  const labelId = useId()
  const hintId = useId()
  const [draft, setDraft] = useState({ from: formatAmount(from), to: formatAmount(to) })

  // A change that did not come from typing (a chip, Clear all, a preset) replaces the draft.
  useEffect(() => {
    setDraft((d) => (parseAmount(d.from) === from && parseAmount(d.to) === to ? d : { from: formatAmount(from), to: formatAmount(to) }))
  }, [from, to])

  const draftFrom = parseAmount(draft.from)
  const draftTo = parseAmount(draft.to)
  const invalid = rangeError(draftFrom, draftTo)
  const marker = salaryMarker(filters, profile)
  const hint = invalid ? RANGE_ERROR_TEXT : describeRange(draftFrom, draftTo)

  const edit = (next) => {
    setDraft(next)
    const f = parseAmount(next.from)
    const t = parseAmount(next.to)
    if (!rangeError(f, t)) onChange({ ...SALARY_CLEARED, salaryMode: f == null && t == null ? 'cleared' : 'set', salaryFrom: f ?? '', salaryTo: t ?? '' })
  }
  const input = (side, name) => (
    <input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      aria-label={name}
      aria-invalid={invalid}
      aria-describedby={hintId}
      placeholder={side === 'from' ? 'From' : 'To'}
      value={draft[side]}
      onChange={(e) => edit({ ...draft, [side]: sanitizeAmount(e.target.value) })}
      onBlur={() => setDraft((d) => ({ ...d, [side]: formatAmount(parseAmount(d[side])) }))}
      className="w-full min-w-0 bg-transparent px-1 py-2.5 text-sm focus:outline-none dark:text-stone-50"
    />
  )

  return (
    <div className={className}>
      <div className="mb-1.5 flex items-center gap-1">
        <span id={labelId} className="text-sm font-medium text-stone-700 dark:text-stone-300">Salary (EUR/month)</span>
        <InfoTip text={FILTER_HELP.salary} label="About Salary" />
        {marker === 'profile' && (
          <span
            role="img"
            aria-label="Taken from your profile"
            title="Taken from your profile"
            className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-amber-100 text-[11px] font-bold leading-none text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
          >
            !
          </span>
        )}
      </div>
      <div
        role="group"
        aria-labelledby={labelId}
        className={`flex items-center gap-1 rounded-lg border px-3 focus-within:ring-2 focus-within:ring-teal-500/30 dark:bg-stone-950 ${invalid ? 'border-red-400' : 'border-stone-300 dark:border-stone-700'}`}
      >
        {input('from', 'Salary from, EUR per month')}
        <span aria-hidden="true" className="text-stone-400">–</span>
        {input('to', 'Salary to, EUR per month')}
        <span className="shrink-0 text-xs text-stone-500">EUR/mo</span>
        {(draft.from !== '' || draft.to !== '') && (
          <button
            type="button"
            aria-label="Clear salary range"
            onClick={() => edit({ from: '', to: '' })}
            className="shrink-0 rounded-full p-1 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      </div>
      <p id={hintId} className={`mt-1 min-h-[1rem] text-xs ${invalid ? 'text-red-500' : 'text-stone-500'}`}>{hint}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {SALARY_PRESETS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => edit({ from: formatAmount(n), to: '' })}
            className="rounded-full border border-stone-300 px-2.5 py-0.5 text-xs text-stone-700 hover:border-teal-400 dark:border-stone-700 dark:text-stone-300"
          >
            {n}+
          </button>
        ))}
        <label className="ml-1 flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
          <input
            type="checkbox"
            checked={includeUnknown}
            onChange={(e) => onChange({ salaryIncludeUnknown: e.target.checked })}
            className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
          />
          Include jobs without salary
        </label>
      </div>
      {marker === 'profile' && <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">{profileSalaryNote(profile)}</p>}
      {(marker === 'differs' || marker === 'cleared') && (
        <p className="mt-1 text-xs text-stone-500">
          {marker === 'cleared' ? 'Cleared.' : 'Differs from your profile.'}{' '}
          <button type="button" onClick={() => onChange(SALARY_RESET)} className="underline underline-offset-2 hover:text-teal-700 dark:hover:text-teal-300">
            Reset to profile
          </button>
        </p>
      )}
    </div>
  )
}
