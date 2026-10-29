import { NEEDS_VISA_STATUSES } from './workAuthorization.js'
import { passesSalaryFilters } from './jobSalary.js'

export function getJobProvider(job) {
  return job.provider || job.site || ''
}

/** The priority filter as a list. A string saved by the old single-select reads as a list of one. */
export function normalizePriorityFilter(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  return value ? [value] : []
}

/**
 * `appliedJobIds` is the set of jobs with a non-voided application (appliedFilter.js); the status
 * value "applied" reads it, since the tracker store, not the job record, says whether a job was applied to.
 */
export function filterJobs(jobs, filters = {}, { appliedJobIds = null } = {}) {
  const {
    searchText = '',
    location = '',
    site = '',
    provider = '',
    remoteOnly = false,
    hideNeedsVisa = false,
    status = '',
    matchLabel = '',
    priority = [],
    minScore = '',
    minSalary = '',
    desiredSalaryMin = '',
    desiredSalaryMax = '',
  } = filters

  const priorities = normalizePriorityFilter(priority)
  const q = searchText.trim().toLowerCase()

  return (jobs || []).filter((job) => {
    if (status === 'applied') {
      if (!appliedJobIds?.has(job.jobId)) return false
    } else if (status && job.status !== status) return false
    if (matchLabel && job.matchLabel !== matchLabel) return false
    if (priorities.length && !priorities.includes(job.priority)) return false
    if (minScore !== '' && minScore != null) {
      const floor = Number(minScore)
      if (!Number.isNaN(floor) && (job.matchScore ?? 0) < floor) return false
    }
    if (!passesSalaryFilters(job, { minSalary, desiredMin: desiredSalaryMin, desiredMax: desiredSalaryMax })) return false
    if (remoteOnly && !job.isRemote) return false
    if (hideNeedsVisa && NEEDS_VISA_STATUSES.has(job.workAuthorization?.status)) return false
    if (site && (job.site || '').toLowerCase() !== site.toLowerCase()) return false
    if (provider && getJobProvider(job).toLowerCase() !== provider.toLowerCase()) return false
    if (location && !(job.location || '').toLowerCase().includes(location.toLowerCase())) return false

    if (q) {
      const haystack = [
        job.title,
        job.company,
        job.location,
        job.site,
        job.provider,
        job.source,
        job.description,
        job.searchTerm,
      ].join(' ').toLowerCase()
      if (!haystack.includes(q)) return false
    }

    return true
  })
}

export function getUniqueSites(jobs) {
  return [...new Set((jobs || []).map((j) => j.site).filter(Boolean))].sort()
}

export function getUniqueProviders(jobs) {
  return [...new Set((jobs || []).map((j) => getJobProvider(j)).filter(Boolean))].sort()
}

export function getUniqueLocations(jobs) {
  return [...new Set((jobs || []).map((j) => j.location).filter(Boolean))].sort()
}
