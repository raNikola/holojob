import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import JobDetailBody from './JobDetailBody'
import ApplicationTrackerPanel from './ApplicationTrackerPanel'
import { autoLoadJobs } from '../../modules/jobs/autoLoadJobs'
import { loadJobs, saveJobs, updateJobRecord, updateJobStatus } from '../../modules/jobs/jobStorage'
import { findRoutedJob, closeJobPage } from '../../modules/jobs/jobRoute'
import { probePipelineApi } from '../../modules/jobs/pipelineRunner'

/** The full-page Job Details at `#/jobs/<jobId>`: the drawer's body in the main column, tracking in a sidebar. */
export default function JobDetailsPage({ jobId }) {
  const [state, setState] = useState(() => loadJobs())
  const [settled, setSettled] = useState(false)
  const [touched, setTouched] = useState(false)
  const [apiAvailable, setApiAvailable] = useState(false)

  useEffect(() => {
    let cancelled = false
    autoLoadJobs(loadJobs()).then(({ state: next, source }) => {
      if (cancelled) return
      if (source !== 'local') setState(next)
      setSettled(true)
    })
    probePipelineApi().then((probe) => { if (!cancelled) setApiAvailable(probe.available) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (touched) saveJobs(state)
  }, [state, touched])

  const handleStatusChange = useCallback((id, status) => {
    setTouched(true)
    setState((prev) => ({ ...prev, jobs: updateJobStatus(prev.jobs, id, status) }))
  }, [])

  const handleJobUpdated = useCallback((updated) => {
    setTouched(true)
    setState((prev) => ({ ...prev, jobs: updateJobRecord(prev.jobs, updated.jobId, updated) }))
  }, [])

  const routed = findRoutedJob(state.jobs, jobId)
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

  const { job } = routed
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
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={handleJobUpdated} onStatusChange={handleStatusChange} includeTracker={false} />
        </main>
        <aside className="min-w-0 self-start lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto" aria-label="Application tracking">
          <ApplicationTrackerPanel job={job} onStatusChange={handleStatusChange} />
        </aside>
      </div>
    </div>
  )
}
