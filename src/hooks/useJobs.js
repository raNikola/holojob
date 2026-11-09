import { useEffect, useSyncExternalStore } from 'react'
import { adoptStored, getJobsSnapshot, getStoredJob, subscribe } from '../modules/jobs/jobsStore'

const listen = (onChange) => subscribe(onChange)

/** The stored job list; re-renders after any write, from this tab or another. */
export function useJobs() {
  return useSyncExternalStore(listen, () => getJobsSnapshot().jobs, () => getJobsSnapshot().jobs)
}

/** One stored job (null when absent), the same object while its content is unchanged. */
export function useStoredJob(jobId) {
  return useSyncExternalStore(listen, () => getStoredJob(jobId), () => getStoredJob(jobId))
}

/**
 * For a screen that still keeps its own list in state and saves it: after a patch from the drawer or the page, or a
 * write from another tab, take the stored fields in. The screen's own saves are ignored.
 */
export function useJobsSync(setState) {
  useEffect(() => subscribe(({ source, removedId }) => {
    if (source === 'save') return
    setState((prev) => {
      const stored = getJobsSnapshot().jobs
      const have = new Set(stored.map((job) => job.jobId))
      // A hand-entered job is stored before any screen holds it, so one missing from another tab's write was deleted there.
      const alive = prev.jobs.filter((job) => job.jobId !== removedId && !(source === 'storage' && job.manualEntry && !have.has(job.jobId)))
      return { ...prev, jobs: adoptStored(alive, stored) }
    })
  }), [setState])
}
