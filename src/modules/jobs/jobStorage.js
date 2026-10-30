/** @typedef {import('../../types/career-os.d.ts').Job} Job */
import { salaryModeOf } from './salaryFilter.js'
import { normalizeMultiFilter, normalizePriorityFilter } from './jobFilters.js'
import { MANUAL_FIELDS, normalizeJobUrl } from './manualJob.js'

export const JOBS_STORAGE_KEY = 'job-dashboard-discovered-jobs'

export const JOB_STATUSES = ['new', 'saved', 'rejected', 'applied_manually']

const DEFAULT_FILTERS = {
  searchText: '',
  location: '',
  site: [],
  provider: [],
  remoteOnly: false,
  hideNeedsVisa: false,
  hideNoLongerListed: false,
  status: '',
  matchLabel: '',
  priority: [],
  minScore: '',
  // salaryMode: untouched | set | cleared (salaryFilter.js). salaryFrom / salaryTo (EUR per month) exist
  // once the range has been edited; state saved by the three-field panel is read by `salaryModeOf`.
  salaryMode: 'untouched',
  salaryIncludeUnknown: true,
}

export function getDefaultJobsState() {
  return {
    meta: null,
    jobs: [],
    filters: { ...DEFAULT_FILTERS },
    importedAt: null,
  }
}

/** @returns {{ meta: object|null, jobs: Job[], filters: object, importedAt: string|null }} */
export function loadJobs() {
  try {
    const raw = localStorage.getItem(JOBS_STORAGE_KEY)
    if (!raw) return getDefaultJobsState()
    const parsed = JSON.parse(raw)
    return {
      ...getDefaultJobsState(),
      ...parsed,
      filters: { ...DEFAULT_FILTERS, ...parsed.filters, priority: normalizePriorityFilter(parsed.filters?.priority), salaryMode: salaryModeOf(parsed.filters || {}), site: normalizeMultiFilter(parsed.filters?.site), provider: normalizeMultiFilter(parsed.filters?.provider) },
      jobs: Array.isArray(parsed.jobs) ? parsed.jobs : [],
    }
  } catch {
    return getDefaultJobsState()
  }
}

// Read again from the scored-jobs file on every load while the API is up; the
// browser alone holds status, tracking, assets, outreach and filters, never these.
export const FILE_FIELDS = ['description', 'llmFacts', 'engineShadow']

/** The job without the fields the scored-jobs file carries in full. */
export function slimJob(job) {
  const slim = { ...job }
  for (const field of FILE_FIELDS) delete slim[field]
  return slim
}

const savedListeners = new Set()

/** Calls `listener` after every successful `saveJobs`; the jobs store uses it to tell mounted views. Returns the unsubscribe. */
export function onJobsSaved(listener) {
  savedListeners.add(listener)
  return () => savedListeners.delete(listener)
}

/**
 * Stores the job list. When it does not fit in localStorage (about 5M
 * characters; a few hundred enriched ads pass that), stores it without the
 * fields the file restores, and failing that keeps the list in memory only.
 */
export function saveJobs(state, storage = globalThis.localStorage) {
  const payload = {
    meta: state.meta,
    jobs: state.jobs,
    filters: state.filters,
    importedAt: state.importedAt,
  }
  let saved = false
  try {
    storage.setItem(JOBS_STORAGE_KEY, JSON.stringify(payload))
    saved = true
  } catch {
    try {
      storage.setItem(JOBS_STORAGE_KEY, JSON.stringify({ ...payload, jobs: payload.jobs.map(slimJob), slim: true }))
      saved = true
    } catch (error) {
      console.warn(`Job list not saved in this browser: ${error.message}`)
    }
  }
  if (saved) savedListeners.forEach((listener) => listener())
  return payload
}

function jobMatchKey(job) {
  const url = (job.jobUrl || '').trim().toLowerCase()
  if (url) return `url:${url}`
  return `tcl:${(job.title || '').toLowerCase()}|${(job.company || '').toLowerCase()}|${(job.location || '').toLowerCase()}`
}

export function mergeStatusOnImport(existingJobs, incomingJobs) {
  const preservedByKey = new Map()
  const preservedById = new Map()
  for (const job of existingJobs || []) {
    const entry = {
      status: job.status || 'new',
      applicationTracking: job.applicationTracking,
      tailoredAssets: job.tailoredAssets,
      aiInsights: job.aiInsights,
      outreach: job.outreach,
      manual: Object.fromEntries(MANUAL_FIELDS.filter((f) => f in job).map((f) => [f, job[f]])),
    }
    preservedByKey.set(jobMatchKey(job), entry)
    if (job.jobId) preservedById.set(job.jobId, entry)
  }

  return incomingJobs.map((job) => {
    const key = jobMatchKey(job)
    const preserved = preservedById.get(job.jobId) ?? preservedByKey.get(key)
    return {
      ...job,
      ...preserved?.manual,
      status: preserved?.status || job.status || 'new',
      applicationTracking: preserved?.applicationTracking || job.applicationTracking,
      tailoredAssets: job.tailoredAssets || preserved?.tailoredAssets,
      aiInsights: job.aiInsights || preserved?.aiInsights,
      outreach: job.outreach || preserved?.outreach,
    }
  })
}

export function parseJobsFile(json) {
  if (Array.isArray(json)) {
    return { meta: null, jobs: json }
  }
  if (json && Array.isArray(json.jobs)) {
    return { meta: json.meta || null, jobs: json.jobs }
  }
  throw new Error('Invalid discovered_jobs.json format. Expected { meta, jobs } or an array.')
}

export function importJobsFromFile(json, existingState = null) {
  const { meta, jobs } = parseJobsFile(json)
  const prior = existingState?.jobs || []
  // A file row with the address of a hand-entered job is that job under another id (a discovery run found the same
  // posting): the hand-entered one stays, so the list has one row for it.
  const manualAt = new Map(prior.filter((job) => job.manualEntry).map((job) => [normalizeJobUrl(job.jobUrl), job.jobId]).filter(([url]) => url))
  const incoming = jobs.filter((job) => {
    const owner = manualAt.get(normalizeJobUrl(job.jobUrl))
    return !owner || owner === job.jobId
  })
  const merged = mergeStatusOnImport(prior, incoming)
  // A hand-entered job the file lacks (saved while the server was away) is not dropped by a re-import.
  const present = new Set(merged.map((job) => job.jobId))
  const kept = prior.filter((job) => job.manualEntry && !present.has(job.jobId))
  return {
    meta: meta || existingState?.meta || null,
    jobs: [...merged, ...kept],
    filters: existingState?.filters || { ...DEFAULT_FILTERS },
    importedAt: new Date().toISOString(),
  }
}

export function updateJobStatus(jobs, jobId, status) {
  if (!JOB_STATUSES.includes(status)) return jobs
  return jobs.map((job) => (job.jobId === jobId ? { ...job, status } : job))
}

/**
 * Merge `patch` into one job. `applicationTracking` in the patch is ignored: since the application
 * store took over (TRACKER_PLAN S2) the legacy field is never written, and a screen that hands
 * back a row with tracking derived from the store must not save it into the job.
 */
export function updateJobRecord(jobs, jobId, patch) {
  const { applicationTracking: _derived, ...rest } = patch
  return jobs.map((job) => (job.jobId === jobId ? { ...job, ...rest } : job))
}

export function updateJobAiInsights(jobs, jobId, insightsPatch) {
  return jobs.map((job) => {
    if (job.jobId !== jobId) return job
    return {
      ...job,
      aiInsights: {
        ...(job.aiInsights || {}),
        ...insightsPatch,
        updatedAt: new Date().toISOString(),
      },
    }
  })
}

export function updateJobOutreach(jobs, jobId, updater) {
  return jobs.map((job) => {
    if (job.jobId !== jobId) return job
    const current = job.outreach || { contacts: [], messages: [], activity: [], status: 'none' }
    const next = typeof updater === 'function' ? updater(current) : { ...current, ...updater }
    return { ...job, outreach: { ...next, lastUpdated: new Date().toISOString() } }
  })
}

export function updateFilters(state, filters) {
  return {
    ...state,
    filters: { ...state.filters, ...filters },
  }
}
