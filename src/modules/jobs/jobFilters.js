import { NEEDS_VISA_STATUSES } from './workAuthorization.js'
import { describeRange, matchesSalary, salaryRangeOf } from './salaryFilter.js'
import geography from '../../data/geography.json'

export function getJobProvider(job) {
  return job.provider || job.site || ''
}

/** What the Provider filter compares: a job added by hand is "manual" (the flag, not its Source URL), any other its connector. */
const providerOf = (job) => (job?.manualEntry === true ? 'manual' : getJobProvider(job))
export const MANUAL_PROVIDER = 'Manual'

const foldName = (text) => String(text ?? '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/^[ .]+|[ .]+$/g, '')
const COUNTRY_NAMES = new Set(geography.countries.flatMap((c) => [c.name, ...(c.aliases || [])]).map(foldName))
const COUNTRY_JOINERS = new Set(['of', 'in', 'for', 'de', 'du'])

/**
 * The company without a trailing country, as the dedupe key does it (python/job_discovery/dedupe_jobs.py `_company_name`):
 * "Fivetran Serbia" is Fivetran's Serbian entity. A name that ends "of <country>" ("Bank of Serbia") is the country's own and stays whole.
 * `name` keeps the writing of the first words; `key` is lower-case with single spaces.
 */
export function companyParts(value) {
  const words = String(value ?? '').trim().split(/\s+/).filter(Boolean)
  const lower = words.map((w) => w.toLowerCase())
  for (const size of [2, 1]) {
    if (lower.length > size && COUNTRY_NAMES.has(foldName(lower.slice(-size).join(' ')))) {
      const rest = lower.slice(0, -size)
      if (!COUNTRY_JOINERS.has(rest[rest.length - 1])) return { name: words.slice(0, -size).join(' '), key: rest.join(' ') }
    }
  }
  return { name: words.join(' '), key: lower.join(' ') }
}

/** The Company filter's entries, one per company, `{ value, label }` with the number of jobs in `jobs`, sorted by name. */
export function getCompanyOptions(jobs) {
  const entries = new Map()
  for (const job of jobs || []) {
    const { name, key } = companyParts(job.company)
    if (!key) continue
    const entry = entries.get(key) || { value: name, count: 0 }
    entry.count += 1
    entries.set(key, entry)
  }
  return [...entries.values()]
    .sort((a, b) => a.value.localeCompare(b.value, undefined, { sensitivity: 'base' }))
    .map(({ value, count }) => ({ value, label: `${value} (${count})` }))
}

/** A multi-value filter as a list. A string saved by an older single-select reads as a list of one. */
export function normalizeMultiFilter(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  return value ? [value] : []
}

export const normalizePriorityFilter = normalizeMultiFilter

/**
 * A job that was seen in an earlier search and has since disappeared from its source (`isClosed`, set by
 * python/job_scoring/job_history.py). That is not proof the position is closed. Nothing else counts, so a
 * job with no such field stays; the match score, location and work-authorization status play no part.
 */
export function isNoLongerListed(job) {
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
    company = [],
    remoteOnly = false,
    hideNeedsVisa = false,
    hideNoLongerListed = false,
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
  const companies = new Set(normalizeMultiFilter(company).map((c) => companyParts(c).key))
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
    if (hideNoLongerListed && isNoLongerListed(job)) return false
    if (hideNeedsVisa && NEEDS_VISA_STATUSES.has(job.workAuthorization?.status)) return false
    if (sites.size && !sites.has((job.site || '').toLowerCase())) return false
    if (providers.size && !providers.has(providerOf(job).toLowerCase())) return false
    if (companies.size && !companies.has(companyParts(job.company).key)) return false
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

/** The connectors present in `jobs`, sorted; "Manual" (jobs added by hand) is listed first when there are any. */
export function getUniqueProviders(jobs) {
  const all = new Set((jobs || []).map((j) => providerOf(j)).filter(Boolean))
  const hasManual = all.delete('manual')
  return [...(hasManual ? [MANUAL_PROVIDER] : []), ...[...all].sort()]
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
  const companies = normalizeMultiFilter(filters.company)
  if (companies.length) add('company', `Company: ${companies.join(', ')}`, { company: [] })
  if (filters.matchLabel) add('matchLabel', `Match label: ${filters.matchLabel}`, { matchLabel: '' })
  const { from, to } = salaryRangeOf(filters)
  if (from != null || to != null) {
    const hidesUnknown = filters.salaryIncludeUnknown === false ? ', jobs without salary hidden' : ''
    add('salary', `Salary: ${describeRange(from, to)}${hidesUnknown}`, SALARY_CLEARED)
  }
  if (filters.hideNoLongerListed) add('hideNoLongerListed', 'Hiding jobs no longer listed', { hideNoLongerListed: false })
  if (filters.hideNeedsVisa) add('hideNeedsVisa', 'Hiding jobs that need a visa', { hideNeedsVisa: false })
  return chips
}

/**
 * Clears the salary range. Explicit '' (not null) so the profile's figures do not refill it, and the
 * three fields of the old panel are reset so nothing stale is left behind. The "include jobs without
 * salary" checkbox is not touched.
 */
export const SALARY_CLEARED = { salaryMode: 'cleared', salaryFrom: '', salaryTo: '', minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null }

/**
 * Gives the salary back to the profile: untouched again, so the profile's current figures apply (they are
 * read at render, not copied), and the checkbox is ON.
 */
export const SALARY_RESET = {
  salaryMode: 'untouched', salaryFrom: null, salaryTo: null, minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null, salaryIncludeUnknown: true,
}

/** The patch that clears every filter. Salary fields become '' (not null) so the profile's figures do not refill them. */
export const CLEAR_ALL_FILTERS = {
  searchText: '',
  location: '',
  site: [],
  provider: [],
  company: [],
  remoteOnly: false,
  hideNeedsVisa: false,
  hideNoLongerListed: false,
  status: '',
  matchLabel: '',
  priority: [],
  minScore: '',
  ...SALARY_CLEARED,
  salaryIncludeUnknown: true,
}

/** Filters inside "More filters" that are active, so the toggle can show a count. */
export const MORE_FILTER_KEYS = ['provider', 'company', 'matchLabel', 'salary', 'hideNeedsVisa', 'hideNoLongerListed']
export function moreFiltersCount(chips) {
  return chips.filter((c) => MORE_FILTER_KEYS.includes(c.key)).length
}
