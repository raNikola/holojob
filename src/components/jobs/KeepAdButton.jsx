import { useState } from 'react'
import { Bookmark, Loader2 } from 'lucide-react'
import Alert from '../ui/Alert'
import { KEEP_FAILED, keepAd } from '../../modules/jobs/keepAd'
import { writeJobState } from '../../modules/jobs/jobStateClient'

/** Keeps a row only the server holds. Nothing else stores one; opening it does not. On success the stored row takes over everywhere. */
export default function KeepAdButton({ row }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const keep = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    const result = await keepAd(row).catch(() => ({ ok: false, message: KEEP_FAILED }))
    if (!result.ok) setError(result.message)
    // Mirror the flag to the server. A failure leaves the ad kept here and shows the "not on the server yet" notice until it is imported.
    else writeJobState(result.job, { keep: true }).catch(() => {})
    setBusy(false)
  }
  return (
    <span className="inline-flex flex-col items-start gap-1" onClick={(e) => e.stopPropagation()}>
      <button type="button" disabled={busy} onClick={keep} className="inline-flex items-center gap-1 rounded-md border border-teal-600 px-2 py-1 text-xs font-medium text-teal-700 hover:bg-teal-50 disabled:opacity-50 dark:text-teal-300 dark:hover:bg-teal-950">
        {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <Bookmark className="h-3 w-3" aria-hidden="true" />}
        Keep this ad
      </button>
      {error && <Alert variant="error">{error}</Alert>}
    </span>
  )
}
