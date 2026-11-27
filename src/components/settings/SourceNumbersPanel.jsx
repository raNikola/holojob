import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { fetchSources, saveSourceNumbers } from '../../modules/sources/sourcesClient'
import { numbersChanges, numbersDraftFrom } from '../../modules/sources/numberSettings'

const INPUT = 'w-24 rounded-lg border border-stone-300 bg-white px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-900'

/** Two number fields; no fetching, so it renders the same in tests. */
export function SourceNumberFields({ data, draft, onChange, errors = {}, disabled = false }) {
  const limits = data?.limits ?? {}
  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="retry-max-total" className="block text-sm font-medium text-stone-800 dark:text-stone-200">Description retries per ad</label>
        <input id="retry-max-total" inputMode="numeric" className={INPUT} value={draft.maxTotal} disabled={disabled} onChange={(e) => onChange({ ...draft, maxTotal: e.target.value })} />
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
          How many times an ad with an empty description is read again, one retry per scan (0 turns it off, up to {limits.retryMax}; default {limits.retryDefault}). An empty reply never means the ad has expired.
        </p>
        {errors.maxTotal && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{errors.maxTotal}</p>}
      </div>
      <div>
        <label htmlFor="repost-window-days" className="block text-sm font-medium text-stone-800 dark:text-stone-200">Repost window (days)</label>
        <input id="repost-window-days" inputMode="numeric" className={INPUT} value={draft.repostWindowDays} disabled={disabled} onChange={(e) => onChange({ ...draft, repostWindowDays: e.target.value })} />
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
          Two ads of one company and title on the same board count as a repost when they were posted within this many days (1 to {limits.repostWindowMax}; default {limits.repostWindowDefault}). It only sets the count shown on a row; no row is merged.
        </p>
        {errors.repostWindowDays && <p className="mt-1 text-xs text-red-700 dark:text-red-300">{errors.repostWindowDays}</p>}
      </div>
    </div>
  )
}

export default function SourceNumbersPanel() {
  const [data, setData] = useState(null)
  const [draft, setDraft] = useState({ maxTotal: '', repostWindowDays: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  const apply = useCallback((answer) => {
    setData(answer)
    setDraft(numbersDraftFrom(answer))
    setError(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchSources().then((result) => {
      if (cancelled) return
      if (result.ok) apply(result.data)
      else setError(result.data?.error || 'Pipeline API offline: these settings cannot be read or changed.')
    })
    return () => { cancelled = true }
  }, [apply])

  const { payload, errors } = data ? numbersChanges(draft, data) : { payload: null, errors: {} }

  const handleSave = async () => {
    if (!payload) return
    setBusy(true)
    setMessage(null)
    const result = await saveSourceNumbers(payload)
    setBusy(false)
    if (result.ok) {
      apply(result.data)
      setMessage('Saved. The next scan and the next list read use these values.')
    } else {
      setError(result.data?.errors?.join('; ') || result.data?.error || 'Not saved.')
    }
  }

  return (
    <Card title="Retries and reposts" description="Two numbers the scan and the list read. They change no score and no filter.">
      {!data && !error && <p className="text-sm text-stone-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading…</p>}
      {data && <SourceNumberFields data={data} draft={draft} errors={errors} disabled={busy} onChange={setDraft} />}
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={handleSave} disabled={busy || !payload}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          Save
        </Button>
        {message && <p className="text-xs text-teal-700 dark:text-teal-300">{message}</p>}
      </div>
      {error && <div className="mt-3"><Alert variant="error">{error}</Alert></div>}
    </Card>
  )
}
