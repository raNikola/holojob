import { useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import Alert from '../ui/Alert'
import { rescoreKeptAd } from '../../modules/jobs/keptRescore'

/** "Re-score this ad" for a kept ad: local scoring on the server, only when clicked. Keep, notes and applications are untouched. */
export default function KeptRescoreButton({ job, onJobUpdated, disabled = false }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  if (job.keptByUser !== true) return null
  const run = async () => {
    if (busy) return
    setBusy(true)
    setMessage(null)
    const result = await rescoreKeptAd(job.jobId).catch(() => ({ ok: false, message: 'The ad could not be re-scored. Its saved score is unchanged.' }))
    if (result.ok) onJobUpdated?.(result.job)
    else setMessage(result.message)
    setBusy(false)
  }
  return (
    <div className="flex flex-col items-start gap-1">
      <button type="button" disabled={busy || disabled} onClick={run} className="inline-flex items-center gap-1 rounded-md border border-teal-600 px-2 py-1 text-xs font-medium text-teal-700 hover:bg-teal-50 disabled:opacity-50 dark:text-teal-300 dark:hover:bg-teal-950">
        {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-3 w-3" aria-hidden="true" />}
        {typeof job.matchScore === 'number' || job.dataStatus ? 'Re-score this ad' : 'Score this ad'}
      </button>
      <p className="text-xs text-stone-500">Scores the kept ad on this server. No AI call is made, and Keep, notes and applications stay as they are.</p>
      {message && <Alert variant="error">{message}</Alert>}
    </div>
  )
}
