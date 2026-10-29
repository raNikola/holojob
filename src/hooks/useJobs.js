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
  useEffect(() => subscribe(({ source }) => {
    if (source === 'save') return
    setState((prev) => ({ ...prev, jobs: adoptStored(prev.jobs, getJobsSnapshot().jobs) }))
  }), [setState])
}
