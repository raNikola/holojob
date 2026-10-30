import { NEEDS_VISA_STATUSES } from './workAuthorization.js'
import { describeRange, matchesSalary, salaryRangeOf } from './salaryFilter.js'

export function getJobProvider(job) {
  return job.provider || job.site || ''
}

/** A multi-value filter as a list. A string saved by an older single-select reads as a list of one. */
export function normalizeMultiFilter(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  return value ? [value] : []
}

export const normalizePriorityFilter = normalizeMultiFilter

/**
 * A job discovery has confirmed closed: it was seen before and is no longer listed (`isClosed`, set by
 * python/job_scoring/job_history.py). Nothing else counts, so a job with no such field stays; the match
 * score, location and work-authorization status play no part.
 */
export function isConfirmedClosed(job) {
  return job?.isClosed === true
}

const lowerSet = (values) => new Set(values.map((v) => String(v).toLowerCase()))

/**
 * `appliedJobIds` is the set of jobs with a non-voided application (appliedFilter.js); the status
 * value "applied" reads it, since the tracker store, not the job record, says whether a job was applied to.
 */
export function filterJobs(jobs, filters = {}, { appliedJobIds = null } = {}) {
  const {
    searchText = '',
    location = '',
    site = [],
    provider = [],
    remoteOnly = false,
    hideNeedsVisa = false,
    hideClosed = false,
    status = '',
    matchLabel = '',
    priority = [],
    minScore = '',
    salaryIncludeUnknown = true,
  } = filters

  const salaryRange = salaryRangeOf(filters)
  const priorities = normalizePriorityFilter(priority)
  const sites = lowerSet(normalizeMultiFilter(site))
  const providers = lowerSet(normalizeMultiFilter(provider))
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
    if (!matchesSalary(job.salaryMonthlyEur, salaryRange, salaryIncludeUnknown !== false)) return false
    if (remoteOnly && !job.isRemote) return false
    if (hideClosed && isConfirmedClosed(job)) return false
    if (hideNeedsVisa && NEEDS_VISA_STATUSES.has(job.workAuthorization?.status)) return false
    if (sites.size && !sites.has((job.site || '').toLowerCase())) return false
    if (providers.size && !providers.has(getJobProvider(job).toLowerCase())) return false
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

/** How many jobs carry each of `values` in `field`, over the whole list (no other filter applies). Values with no job are left out. */
export function countByValue(jobs, field, values) {
  const counts = new Map()
  for (const job of jobs || []) counts.set(job[field], (counts.get(job[field]) || 0) + 1)
  return values.filter((v) => counts.has(v)).map((value) => ({ value, count: counts.get(value) }))
}

const isSet = (v) => v !== '' && v != null

/**
 * The active filters as chips: `{ key, label, patch }`, where `patch` resets that filter. Pure.
 * A salary field that is `null` means "use the profile's figure" and `withProfileSalaryDefaults`
 * has already replaced it, so what reaches here is the effective value; clearing sets '' (an
 * explicit empty), never null, or the profile figure would come straight back.
 */
export function activeFilterChips(filters = {}) {
  const chips = []
  const add = (key, label, patch) => chips.push({ key, label, patch })
  if (filters.searchText?.trim()) add('searchText', `Search: ${filters.searchText.trim()}`, { searchText: '' })
  if (filters.location?.trim()) add('location', `Location: ${filters.location.trim()}`, { location: '' })
  const sites = normalizeMultiFilter(filters.site)
  if (sites.length) add('site', `Source: ${sites.join(', ')}`, { site: [] })
  if (filters.status) add('status', `Status: ${filters.status}`, { status: '' })
  const priorities = normalizePriorityFilter(filters.priority)
  if (priorities.length) add('priority', `Priority: ${priorities.join(', ')}`, { priority: [] })
  if (isSet(filters.minScore)) add('minScore', `Min score: ${filters.minScore}`, { minScore: '' })
  if (filters.remoteOnly) add('remoteOnly', 'Remote only', { remoteOnly: false })
  const providers = normalizeMultiFilter(filters.provider)
  if (providers.length) add('provider', `Provider: ${providers.join(', ')}`, { provider: [] })
  if (filters.matchLabel) add('matchLabel', `Match label: ${filters.matchLabel}`, { matchLabel: '' })
  const { from, to } = salaryRangeOf(filters)
  if (from != null || to != null) {
    const hidesUnknown = filters.salaryIncludeUnknown === false ? ', jobs without salary hidden' : ''
    add('salary', `Salary: ${describeRange(from, to)}${hidesUnknown}`, SALARY_CLEARED)
  }
  if (filters.hideClosed) add('hideClosed', 'Hiding closed jobs', { hideClosed: false })
  if (filters.hideNeedsVisa) add('hideNeedsVisa', 'Hiding jobs that need a visa', { hideNeedsVisa: false })
  return chips
}

/**
 * Clears the salary range. Explicit '' (not null) so the profile's figures do not refill it, and the
 * three fields of the old panel are reset so nothing stale is left behind. The "include jobs without
 * salary" checkbox is not touched.
 */
export const SALARY_CLEARED = { salaryFrom: '', salaryTo: '', minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null }

/** The patch that clears every filter. Salary fields become '' (not null) so the profile's figures do not refill them. */
export const CLEAR_ALL_FILTERS = {
  searchText: '',
  location: '',
  site: [],
  provider: [],
  remoteOnly: false,
  hideNeedsVisa: false,
  hideClosed: false,
  status: '',
  matchLabel: '',
  priority: [],
  minScore: '',
  ...SALARY_CLEARED,
  salaryIncludeUnknown: true,
}

/** Filters inside "More filters" that are active, so the toggle can show a count. */
export const MORE_FILTER_KEYS = ['provider', 'matchLabel', 'salary', 'hideNeedsVisa', 'hideClosed']
export function moreFiltersCount(chips) {
  return chips.filter((c) => MORE_FILTER_KEYS.includes(c.key)).length
}
