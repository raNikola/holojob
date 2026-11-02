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
import { loadJobSources, resolveJob } from '../../modules/jobs/jobResolve'
import { formatSeen } from '../../modules/jobs/jobHistory'
import { loadJobHistory, loadLatestDiscoveredJobs, probePipelineApi } from '../../modules/jobs/pipelineRunner'
import { applicationsForJob } from '../../modules/applications/trackingView'
import { useApplications } from '../../hooks/useApplications'
import { useStoredJob } from '../../hooks/useJobs'
import { useJobPatcher } from '../../hooks/useJobPatcher'

/** Says the ad is not in the latest results, and what still works. Never a claim that the ad closed. */
function NotInLatestRun({ resolved }) {
  const { lastSeen, capturedAt, readOnly } = resolved
  const when = lastSeen
    ? `Last seen ${formatSeen(lastSeen)}.`
    : `Last-seen date not recorded.${capturedAt ? ` The ad was saved with your application on ${formatSeen(capturedAt)}.` : ''}`
  return (
    <Alert variant="info" title="Not in the latest run">
      {when}
      {readOnly && ' This is the saved copy of the ad. Notes, follow-ups and history work as usual.'}
    </Alert>
  )
}

/**
 * The full-page Job Details at `#/jobs/<jobId>`: the drawer's body in the main column, tracking in a sidebar.
 * The job comes from the first source that has it (`jobResolve.js`): stored row, file, ledger, the application's frozen
 * posting. Writes are field-level patches on the stored record, so a job with no stored row shows no section that writes
 * job fields; the tracker panel writes to the application store and needs no row.
 */
export default function JobDetailsPage({ jobId }) {
  const stored = useStoredJob(jobId)
  const applications = useApplications()
  const [sources, setSources] = useState(null)
  const [apiAvailable, setApiAvailable] = useState(false)

  useEffect(() => {
    let cancelled = false
    loadJobSources(jobId, loadJobs(), { autoLoad: autoLoadJobs, loadDiscovered: loadLatestDiscoveredJobs, loadHistory: loadJobHistory }).then((found) => {
      if (cancelled) return
      // a job the file knows and this browser does not: add it, never replace a stored record. A fallback is not added.
      if (found.addable) addJobIfAbsent(found.addable)
      const fromFile = found.row ?? found.fileJob
      const fileFields = fromFile ? Object.fromEntries(FILE_FIELDS.filter((f) => f in fromFile).map((f) => [f, fromFile[f]])) : null
      setSources({ ...found, fileFields })
    })
    probePipelineApi().then((probe) => { if (!cancelled) setApiAvailable(probe.available) })
    return () => { cancelled = true }
  }, [jobId])

  const storeReady = applications.status === 'ready'
  const resolved = useMemo(() => resolveJob({
    stored,
    fileFields: sources?.fileFields,
    fileJob: sources?.fileJob,
    ledger: sources?.ledger,
    applications: storeReady ? applicationsForJob(applications.store, jobId) : [],
    fileChecked: sources?.fileChecked,
    inFile: sources?.inFile,
  }), [stored, sources, storeReady, applications.store, jobId])
  const { job } = resolved
  const { onJobUpdated, onStatusChange } = useJobPatcher(job)

  const routed = findRoutedJob(job ? [job] : [], jobId)
  const settled = Boolean(sources) && (storeReady || applications.status === 'error')
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
      {resolved.notInLatest && <NotInLatestRun resolved={resolved} />}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
        <main className="min-w-0">
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} onStatusChange={onStatusChange} includeTracker={false} includeTailor={!resolved.readOnly} includeAiTools={!resolved.readOnly} includeContacts={!resolved.readOnly} />
        </main>
        <aside className="min-w-0 self-start lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto" aria-label="Application tracking">
          <ApplicationTrackerPanel job={job} onStatusChange={onStatusChange} />
        </aside>
      </div>
    </div>
  )
}
