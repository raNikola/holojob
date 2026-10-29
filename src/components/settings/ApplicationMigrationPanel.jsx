import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { loadJobs } from '../../modules/jobs/jobStorage'
import { previewMigration, runMigration } from '../../modules/applications/migrationClient'

const COUNT_LABELS = [
  ['scanned', 'Jobs scanned'],
  ['ignored', 'No tracking'],
  ['candidates', 'Tracked'],
  ['created', 'To migrate'],
  ['alreadyMigrated', 'Already migrated'],
  ['alreadyTracked', 'Already tracked'],
  ['unmappable', 'Cannot be mapped'],
]

/** Settings: migrate the old per-job tracking into the application store (TRACKER_PLAN 2). */
export default function ApplicationMigrationPanel() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [plan, setPlan] = useState(null)
  const [done, setDone] = useState(null)

  const handlePreview = async () => {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      const { jobs } = loadJobs()
      setPlan({ jobs, ...(await previewMigration(jobs)) })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleRun = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await runMigration(plan.jobs, plan.previewSha)
      setDone(result)
      setPlan(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const flagged = plan?.entries.filter((e) => e.warnings.length || e.action === 'unmappable') ?? []

  return (
    <Card title="Application tracking migration">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Copies the tracking saved on each job in this browser into the application store on the server. The dry run
        writes nothing; the migration backs up first and can be run again without adding anything.
      </p>
      <div className="flex flex-col gap-3">
        <Button variant="secondary" onClick={handlePreview} disabled={busy}>
          {busy && !plan ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Dry run
        </Button>
        {error && <Alert variant="error">{error}</Alert>}
        {plan && (
          <>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
              {COUNT_LABELS.map(([key, label]) => (
                <div key={key} className="flex justify-between gap-2">
                  <dt className="text-stone-600 dark:text-stone-400">{label}</dt>
                  <dd className="font-medium">{plan.counts[key]}</dd>
                </div>
              ))}
            </dl>
            {flagged.length > 0 && (
              <ul className="max-h-64 space-y-1 overflow-y-auto text-xs text-stone-600 dark:text-stone-400">
                {flagged.map((entry) => (
                  <li key={`${entry.jobId}-${entry.action}`}>
                    <strong>{entry.title || entry.jobId || 'Unknown job'}</strong>
                    {entry.company ? `, ${entry.company}` : ''}: {entry.reason ?? entry.warnings.join('; ')}
                  </li>
                ))}
              </ul>
            )}
            <Button onClick={handleRun} disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              I reviewed the dry run: migrate {plan.counts.created} application{plan.counts.created === 1 ? '' : 's'}
            </Button>
          </>
        )}
        {done && (
          <Alert variant="success">
            Migrated {done.counts.created} application{done.counts.created === 1 ? '' : 's'}. Backup: {done.backupPath}
          </Alert>
        )}
      </div>
    </Card>
  )
}
