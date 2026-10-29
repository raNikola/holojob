import { useCallback } from 'react'
import { patchJob, patchJobFromCopy } from '../modules/jobs/jobsStore'

/**
 * The `onJobUpdated` / `onStatusChange` pair for the components in Job Details. `job` is the copy they render and
 * spread into what they pass back, so only the fields they changed are written, on top of the latest stored record.
 */
export function useJobPatcher(job) {
  const jobId = job?.jobId
  const onJobUpdated = useCallback((next) => {
    if (jobId) patchJobFromCopy(jobId, job, next)
  }, [jobId, job])
  const onStatusChange = useCallback((id, status) => {
    patchJob(id, { status })
  }, [])
  return { onJobUpdated, onStatusChange }
}
