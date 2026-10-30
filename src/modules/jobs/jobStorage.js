/** @typedef {import('../../types/holojob.d.ts').Job} Job */
import { normalizeMultiFilter, normalizePriorityFilter } from './jobFilters.js'

export const JOBS_STORAGE_KEY = 'job-dashboard-discovered-jobs'

export const JOB_STATUSES = ['new', 'saved', 'rejected', 'applied_manually']

const DEFAULT_FILTERS = {
  searchText: '',
  location: '',
  site: [],
  provider: [],
  remoteOnly: false,
  hideNeedsVisa: false,
  status: '',
  matchLabel: '',
  priority: [],
  minScore: '',
  // salaryFrom / salaryTo (EUR per month) are absent until the user touches the range: then the
  // profile's figures apply. A list saved by the three-field panel (minSalary, desiredSalaryMin,
  // desiredSalaryMax) is read as it stands (salaryFilter.js `salaryRangeOf`) until the range is edited.
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
      filters: { ...DEFAULT_FILTERS, ...parsed.filters, priority: normalizePriorityFilter(parsed.filters?.priority), site: normalizeMultiFilter(parsed.filters?.site), provider: normalizeMultiFilter(parsed.filters?.provider) },
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
  for (const job of existingJobs || []) {
    preservedByKey.set(jobMatchKey(job), {
      status: job.status || 'new',
      applicationTracking: job.applicationTracking,
      tailoredAssets: job.tailoredAssets,
      aiInsights: job.aiInsights,
      outreach: job.outreach,
    })
  }

  return incomingJobs.map((job) => {
    const key = jobMatchKey(job)
    const preserved = preservedByKey.get(key)
    return {
      ...job,
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
  const merged = mergeStatusOnImport(prior, jobs)
  return {
    meta: meta || existingState?.meta || null,
    jobs: merged,
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
