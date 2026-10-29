/**
 * The "applied" value of the Jobs status filter (docs/redesign/TRACKER_PLAN.md 2.3, decision 10):
 * a job is applied when the application store holds a non-voided application for it. Pure.
 */

import { isActive } from './foldApplication.js'

/** The filter value. It is not a job status, so `JOB_STATUSES` and `updateJobStatus` never see it. */
export const APPLIED_FILTER = 'applied'
export const LEGACY_APPLIED_STATUS = 'applied_manually'

/** Ids of the jobs that have at least one non-voided application. */
export function appliedJobIds(store) {
  const ids = new Set()
  for (const app of Object.values(store?.applications ?? {})) {
    if (app.posting?.jobId && isActive(app)) ids.add(app.posting.jobId)
  }
  return ids
}

/** True while some job is still `applied_manually` with no application in the store (not migrated yet). */
export function hasUnmigratedApplied(jobs, store) {
  const known = new Set(Object.values(store?.applications ?? {}).map((app) => app.posting?.jobId))
  return (jobs ?? []).some((job) => job.status === LEGACY_APPLIED_STATUS && !known.has(job.jobId))
}

/** The values the Status select offers: the job statuses, with "applied" in place of the legacy one once it is not needed. */
export function statusFilterOptions(jobStatuses, jobs, store) {
  const keepLegacy = hasUnmigratedApplied(jobs, store)
  const base = jobStatuses.filter((s) => s !== LEGACY_APPLIED_STATUS || keepLegacy)
  return [...base, APPLIED_FILTER]
}
