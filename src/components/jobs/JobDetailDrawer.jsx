import { useEffect, useMemo, useState } from 'react'
import { Maximize2, X } from 'lucide-react'
import JobDetailBody from './JobDetailBody'
import Button from '../ui/Button'
import { dirtyDraftLabels, leaveDecision } from '../../modules/jobs/draftGuard'
import ApplicationTrackingSummary from './ApplicationTrackingSummary'
import { canOpenJobPage, MISSING_JOB_HINT, openJobPage } from '../../modules/jobs/jobRoute'
import { hasFallback } from '../../modules/jobs/jobResolve'
import { KEEP_FIRST_NOTE } from '../../modules/jobs/jobListView'
import { stripDisplayFields } from '../../modules/jobs/allAds'
import KeepAdButton from './KeepAdButton'
import { mergeLive } from '../../modules/jobs/jobsStore'
import { loadJobHistory } from '../../modules/jobs/pipelineRunner'
import { useApplications } from '../../hooks/useApplications'
import { useStoredJob } from '../../hooks/useJobs'
import { useJobPatcher } from '../../hooks/useJobPatcher'

/**
 * The quick view. It shows the stored record on top of the row it was opened from and writes only the fields a
 * component changed (`useJobPatcher`), so a stale row can never revert another view's change.
 */
export default function JobDetailDrawer({ job: row, onClose, apiAvailable }) {
  const stored = useStoredJob(row?.jobId)
  const merged = useMemo(() => (row ? mergeLive(row, stored) : null), [row, stored])
  const { onJobUpdated, onStatusChange } = useJobPatcher(merged)
  const applications = useApplications()
  const jobId = row?.jobId
  const [ledger, setLedger] = useState(null)
  const needsLedger = Boolean(jobId) && !stored

  useEffect(() => {
    if (!needsLedger) return undefined
    let cancelled = false
    loadJobHistory(jobId).then((found) => { if (!cancelled) setLedger(found) })
    return () => { cancelled = true }
  }, [jobId, needsLedger])

  // A row only the server holds is shown, never stored: its ad text comes from the ledger, and what would write to it waits for "Keep this ad".
  // Mark Applied does not: an application lives in the application store, with no stored row, here as on Job Details.
  const readOnly = Boolean(row?.serverOnly) && !stored
  const job = readOnly && !merged.description && ledger?.jobId === jobId ? { ...merged, description: ledger.job?.description } : merged
  if (!job) return null

  // The drawer stays open when the owner declines, so nothing typed is lost.
  const store = applications.status === 'ready' ? applications.store : null
  const canOpen = canOpenJobPage(stored, { hasFallback: hasFallback(job.jobId, store, ledger?.jobId === job.jobId ? ledger : null) })
  const openFullDetails = () => {
    if (!canOpen) return
    const question = leaveDecision(dirtyDraftLabels())
    if (question && !window.confirm(question)) return
    openJobPage(job.jobId)
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <aside className="panel-text-up relative flex h-full w-full max-w-[75rem] flex-col overflow-y-auto bg-white shadow-xl dark:bg-stone-950">
        <div className="sticky top-0 flex items-start justify-between border-b border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-950">
          <div>
            <h2 className="font-display text-lg font-semibold text-stone-900 dark:text-stone-100">{job.title}</h2>
            <p className="text-sm text-stone-600 dark:text-stone-400">{job.company}</p>
          </div>
          <div className="flex items-center gap-2">
            <span title={canOpen ? undefined : MISSING_JOB_HINT}>
              <Button variant="secondary" onClick={openFullDetails} disabled={!canOpen}><Maximize2 className="mr-1 inline h-4 w-4" />Open full details</Button>
            </span>
            <button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label="Close details">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="p-4">
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} onStatusChange={onStatusChange} includeAiTools={false} includeContacts={false} includeTracker={false} />
          {readOnly && (
            <div className="mt-5 space-y-2">
              <p className="text-sm text-stone-600 dark:text-stone-400">{KEEP_FIRST_NOTE}</p>
              <KeepAdButton row={row} />
            </div>
          )}
          <div className="mt-5">
            <ApplicationTrackingSummary job={stripDisplayFields(job)} onOpenFull={openFullDetails} canOpenFull={canOpen} />
          </div>
        </div>
      </aside>
    </div>
  )
}
