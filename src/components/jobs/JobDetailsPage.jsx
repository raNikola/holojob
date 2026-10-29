import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import JobDetailBody from './JobDetailBody'
import ApplicationTrackerPanel from './ApplicationTrackerPanel'
import { autoLoadJobs } from '../../modules/jobs/autoLoadJobs'
import { FILE_FIELDS, loadJobs } from '../../modules/jobs/jobStorage'
import { addJobIfAbsent } from '../../modules/jobs/jobsStore'
import { findRoutedJob, closeJobPage } from '../../modules/jobs/jobRoute'
import { probePipelineApi } from '../../modules/jobs/pipelineRunner'
import { useStoredJob } from '../../hooks/useJobs'
import { useJobPatcher } from '../../hooks/useJobPatcher'

/**
 * The full-page Job Details at `#/jobs/<jobId>`: the drawer's body in the main column, tracking in a sidebar.
 * The job is the stored record (jobs store), with the fields the scored-jobs file restores laid under it; every
 * write is a field-level patch on the latest stored record.
 */
export default function JobDetailsPage({ jobId }) {
  const stored = useStoredJob(jobId)
  const [fileFields, setFileFields] = useState(null)
  const [settled, setSettled] = useState(false)
  const [apiAvailable, setApiAvailable] = useState(false)

  useEffect(() => {
    let cancelled = false
    autoLoadJobs(loadJobs()).then(({ state: next, source }) => {
      if (cancelled) return
      const fromFile = source === 'local' ? null : next.jobs.find((j) => j.jobId === jobId)
      if (fromFile) {
        // a job the file knows and this browser does not: add it, never replace a stored record
        addJobIfAbsent(fromFile)
        setFileFields(Object.fromEntries(FILE_FIELDS.filter((f) => f in fromFile).map((f) => [f, fromFile[f]])))
      }
      setSettled(true)
    })
    probePipelineApi().then((probe) => { if (!cancelled) setApiAvailable(probe.available) })
    return () => { cancelled = true }
  }, [jobId])

  const job = useMemo(() => (stored ? { ...fileFields, ...stored } : null), [stored, fileFields])
  const { onJobUpdated, onStatusChange } = useJobPatcher(job)

  const routed = findRoutedJob(job ? [job] : [], jobId)
  const back = (
    <Button variant="secondary" onClick={closeJobPage}><ArrowLeft className="mr-1 inline h-4 w-4" />Back</Button>
  )

  if (routed.status === 'missing') {
    return (
      <div className="space-y-4">
        {back}
        {settled
          ? <Alert variant="info">Job not found: there is no job with the id “{jobId}” in your job list. It may have been removed, or the link is out of date.</Alert>
          : <p className="text-sm text-stone-600 dark:text-stone-400">Loading the job…</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        {back}
        <div>
          <h2 className="font-display text-xl font-semibold text-stone-900 dark:text-stone-100">{job.title}</h2>
          <p className="text-sm text-stone-600 dark:text-stone-400">{job.company}</p>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
        <main className="min-w-0">
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} onStatusChange={onStatusChange} includeTracker={false} />
        </main>
        <aside className="min-w-0 self-start lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto" aria-label="Application tracking">
          <ApplicationTrackerPanel job={job} onStatusChange={onStatusChange} />
        </aside>
      </div>
    </div>
  )
}
