import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { hydrateJobTexts, rowsNeedingText } from '../../modules/jobs/jobTexts.js'
import { loadJobs } from '../../modules/jobs/jobStorage.js'
import { invalidateJobs } from '../../modules/jobs/jobsStore.js'
import { setStorageHealth } from '../../modules/jobs/storageHealth.js'
import { GATE_TEXT } from '../../modules/jobs/storageNoticeText.js'

/**
 * Before any screen is shown: if the browser stored the job list without the ad text of some rows (storage shape lean or minimal), get
 * that text from the server's history first (jobTexts.js). With the list stored whole, or no row to fill, this renders its children at once.
 * What the server could not give is counted for the notice (`textsMissing`); the app still opens.
 */
export default function JobTextGate({ children, fetchFn }) {
  const [wanted] = useState(() => {
    const stored = loadJobs()
    return stored.degraded ? rowsNeedingText(stored.jobs) : []
  })
  const [ready, setReady] = useState(wanted.length === 0)

  useEffect(() => {
    if (wanted.length === 0) return undefined
    let live = true
    hydrateJobTexts(wanted, { fetchFn }).then((result) => {
      if (!live) return
      setStorageHealth({ textsMissing: result.missing.length })
      invalidateJobs() // the stored list is read again, now with the texts in it
      setReady(true)
    })
    return () => { live = false }
  }, [wanted, fetchFn])

  if (ready) return children
  return (
    <div role="status" className="flex min-h-screen items-center justify-center gap-2 text-sm text-stone-600 dark:text-stone-300">
      <Loader2 className="h-4 w-4 animate-spin" />
      {GATE_TEXT(wanted.length)}
    </div>
  )
}
