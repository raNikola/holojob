import { useMemo } from 'react'
import { Maximize2, X } from 'lucide-react'
import JobDetailBody from './JobDetailBody'
import Button from '../ui/Button'
import { dirtyDraftLabels, leaveDecision } from '../../modules/jobs/draftGuard'
import { openJobPage } from '../../modules/jobs/jobRoute'
import { mergeLive } from '../../modules/jobs/jobsStore'
import { useStoredJob } from '../../hooks/useJobs'
import { useJobPatcher } from '../../hooks/useJobPatcher'

/**
 * The quick view. It shows the stored record on top of the row it was opened from and writes only the fields a
 * component changed (`useJobPatcher`), so a stale row can never revert another view's change.
 */
export default function JobDetailDrawer({ job: row, onClose, apiAvailable }) {
  const stored = useStoredJob(row?.jobId)
  const job = useMemo(() => (row ? mergeLive(row, stored) : null), [row, stored])
  const { onJobUpdated, onStatusChange } = useJobPatcher(job)
  if (!job) return null

  // The drawer stays open when the owner declines, so nothing typed is lost.
  const openFullDetails = () => {
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
            <Button variant="secondary" onClick={openFullDetails}><Maximize2 className="mr-1 inline h-4 w-4" />Open full details</Button>
            <button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label="Close details">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="p-4">
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} onStatusChange={onStatusChange} />
        </div>
      </aside>
    </div>
  )
}
