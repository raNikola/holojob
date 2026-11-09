import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { loadJobs } from '../../modules/jobs/jobStorage'
import { exportBrowserState, previewJobStateImport, runJobStateImport } from '../../modules/jobs/jobStateClient'

const COUNT_LABELS = [
  ['scanned', 'Rows scanned'],
  ['ignored', 'Nothing to carry'],
  ['appliedInBrowser', 'Applied (tracker, not here)'],
  ['toAdd', 'To add'],
  ['alreadyThere', 'Already on the server'],
  ['conflicts', 'Differ (server kept)'],
]

/**
 * Settings: copy this browser's statuses and Keep flags to the server (STEP5 2.3, narrow part). Order: export, dry run, confirm.
 * Nothing runs by itself, nothing in the browser is cleared, and the server's own entries always win.
 */
export default function JobStatePanel() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [exported, setExported] = useState(null)
  const [plan, setPlan] = useState(null)
  const [done, setDone] = useState(null)

  const guarded = (fn) => async () => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleExport = guarded(async () => {
    setExported(await exportBrowserState(loadJobs().jobs))
    setPlan(null)
    setDone(null)
  })
  const handlePreview = guarded(async () => {
    const { jobs } = loadJobs()
    setPlan({ jobs, ...(await previewJobStateImport(jobs)) })
    setDone(null)
  })
  const handleRun = guarded(async () => {
    setDone(await runJobStateImport(plan.jobs, plan.previewSha))
    setPlan(null)
  })

  return (
    <Card title="Job statuses and Keep on the server">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Saved, Rejected and Keep are kept in this browser until you copy them to the server. Step 1 saves a private export file on the
        server (ids and flags only). Step 2 is a dry run that writes nothing. Step 3 adds what the server lacks, after a backup; an entry
        the server already has is never changed and nothing is deleted. Applications are not part of this: they are already on the server.
      </p>
      <div className="flex flex-col gap-3">
        <Button variant="secondary" onClick={handleExport} disabled={busy}>1. Export this browser&apos;s statuses</Button>
        {exported && <Alert variant="success">Exported {exported.rows} rows to {exported.path}{exported.invalid ? ` (${exported.invalid} skipped as invalid)` : ''}.</Alert>}
        <Button variant="secondary" onClick={handlePreview} disabled={busy || !exported}>
          {busy && !plan && exported ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          2. Dry run
        </Button>
        {error && <Alert variant="error">{error}</Alert>}
        {plan && (
          <>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
              {COUNT_LABELS.map(([key, label]) => (
                <div key={key} className="flex justify-between gap-2">
                  <dt className="text-stone-600 dark:text-stone-400">{label}</dt>
                  <dd className="font-medium">{plan.counts[key]}</dd>
                </div>
              ))}
            </dl>
            <Button onClick={handleRun} disabled={busy || plan.counts.toAdd === 0}>
              3. I reviewed the dry run: add {plan.counts.toAdd} to the server
            </Button>
          </>
        )}
        {done && <Alert variant="success">{done.changed ? `Added ${done.counts.toAdd}. Backup: ${done.backupPath}` : 'Nothing to add.'}</Alert>}
      </div>
    </Card>
  )
}
