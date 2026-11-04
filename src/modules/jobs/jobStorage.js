/** @typedef {import('../../types/career-os.d.ts').Job} Job */
import { salaryModeOf } from './salaryFilter.js'
import { normalizeMultiFilter, normalizePriorityFilter } from './jobFilters.js'
import { MANUAL_FIELDS, MANUAL_ONLY_FIELDS, identityJobUrl } from './manualJob.js'
import { isBlank, mergeCachedTexts, rememberTexts } from './jobTexts.js'
import { NEAR_RATIO, STORAGE_QUOTA_CHARS, getStorageHealth, setStorageHealth } from './storageHealth.js'

export const JOBS_STORAGE_KEY = 'job-dashboard-discovered-jobs'

export const JOB_STATUSES = ['new', 'saved', 'rejected', 'applied_manually']

const DEFAULT_FILTERS = {
  searchText: '',
  location: '',
  site: [],
  provider: [],
  company: [],
  remoteOnly: false,
  hideNeedsVisa: false,
  hideNoLongerListed: false,
  showOffList: false,
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

/**
 * The stored list. A row stored without its ad text gets it from the text cache when the cache has it (jobTexts.js, the one place where
 * texts are put back), so every reader of the list sees the same rows. `degraded` is how the list was last stored (see `saveJobs`).
 * @returns {{ meta: object|null, jobs: Job[], filters: object, importedAt: string|null, degraded?: 'lean'|'minimal' }}
 */
export function loadJobs() {
  try {
    const raw = localStorage.getItem(JOBS_STORAGE_KEY)
    if (!raw) return getDefaultJobsState()
    const parsed = JSON.parse(raw)
    const jobs = mergeCachedTexts(Array.isArray(parsed.jobs) ? parsed.jobs : [])
    mirrorStoredTier(parsed.degraded, jobs)
    return {
      ...getDefaultJobsState(),
      ...parsed,
      filters: { ...DEFAULT_FILTERS, ...parsed.filters, priority: normalizePriorityFilter(parsed.filters?.priority), salaryMode: salaryModeOf(parsed.filters || {}), site: normalizeMultiFilter(parsed.filters?.site), provider: normalizeMultiFilter(parsed.filters?.provider), company: normalizeMultiFilter(parsed.filters?.company) },
      jobs,
    }
  } catch {
    return getDefaultJobsState()
  }
}

// What the notice says after a reload comes from how the list was stored. A failed save (`error`) is not undone by reading the older copy.
function mirrorStoredTier(degraded, jobs) {
  const level = getStorageHealth().level
  if (level === 'error') return
  const wanted = degraded === 'lean' || degraded === 'minimal' ? degraded : (level === 'lean' || level === 'minimal' ? 'ok' : level)
  const droppedText = degraded ? jobs.filter((job) => !job.manualEntry && isBlank(job.description)).length : 0
  setStorageHealth({ level: wanted, rows: jobs.length, droppedText })
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

// --- how the list is stored (S8a) ----------------------------------------------------------------------------------------------
//
// localStorage holds about 5M characters for the whole site. The list is stored in the first of these shapes that fits:
//   full     every row as it is
//   lean     no `llmFacts` or `engineShadow` (the file and the ledger have them), and no `description` on rows the scored file carries.
//            A kept ad, a row no longer in the file and a hand-entered job keep their text: the file has no copy of those.
//   minimal  as lean, but a kept ad and a no-longer-listed row lose their text too. The ledger has it, and `jobTexts.js` gets it back at
//            start, before any screen is shown. A hand-entered job always keeps its text: it is the owner's own and may not be on the server yet.
// Every other field of every row is stored in every shape: status, notes, outreach, tracking, tailored assets, AI insights, links.
// If not even `minimal` fits, nothing is written, the last saved copy stays where it is, and the notice says so (storageHealth.js).

/** A row whose ad text exists nowhere in the scored file: the browser's copy is the only one next to the ledger's. */
const ownText = (job) => Boolean(job.manualEntry || job.keptByUser || job.offList)

export function leanJob(job) {
  const { llmFacts: _facts, engineShadow: _shadow, ...rest } = job
  if (!ownText(job)) delete rest.description
  return rest
}

export function minimalJob(job) {
  const { llmFacts: _facts, engineShadow: _shadow, ...rest } = job
  if (!job.manualEntry) delete rest.description
  return rest
}

const TIERS = [
  { tier: 'full', shape: (job) => job },
  { tier: 'lean', shape: leanJob },
  { tier: 'minimal', shape: minimalJob },
]

/** The characters the rest of the site's storage takes, for the "near the limit" notice. 0 where the storage cannot be walked. */
function otherKeysChars(storage) {
  try {
    let total = 0
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index)
      if (key !== JOBS_STORAGE_KEY) total += key.length + (storage.getItem(key) ?? '').length
    }
    return total
  } catch {
    return 0
  }
}

const savedListeners = new Set()

/** Calls `listener` after every successful `saveJobs`; the jobs store uses it to tell mounted views. Returns the unsubscribe. */
export function onJobsSaved(listener) {
  savedListeners.add(listener)
  return () => savedListeners.delete(listener)
}

/**
 * Stores the job list in the first shape that fits (see above) and tells the user when it had to be shorter, or could not be stored.
 * Returns the payload it was given, with `saved` (false when nothing was written) and `tier`.
 */
export function saveJobs(state, storage = globalThis.localStorage) {
  const payload = {
    meta: state.meta,
    jobs: state.jobs,
    filters: state.filters,
    importedAt: state.importedAt,
  }
  for (const { tier, shape } of TIERS) {
    const jobs = tier === 'full' ? payload.jobs : payload.jobs.map(shape)
    const json = JSON.stringify(tier === 'full' ? payload : { ...payload, jobs, slim: true, degraded: tier })
    try {
      storage.setItem(JOBS_STORAGE_KEY, json)
    } catch {
      continue
    }
    if (tier !== 'full') rememberTexts(payload.jobs.filter((job, index) => jobs[index].description !== job.description)) // the texts this page still holds
    const percent = Math.round((100 * (json.length + otherKeysChars(storage))) / STORAGE_QUOTA_CHARS)
    const droppedText = tier === 'full' ? 0 : payload.jobs.filter((job, index) => !isBlank(job.description) && isBlank(jobs[index].description)).length
    setStorageHealth({
      level: tier === 'full' ? (percent >= NEAR_RATIO * 100 ? 'near' : 'ok') : tier,
      rows: jobs.length, chars: json.length, percent, droppedText,
    })
    savedListeners.forEach((listener) => listener())
    return { ...payload, saved: true, tier }
  }
  console.warn('Job list not saved in this browser: it is over the storage limit even in its shortest form.')
  setStorageHealth({ level: 'error', rows: payload.jobs.length })
  return { ...payload, saved: false, tier: null }
}

export function jobMatchKey(job) {
  const url = (job.jobUrl || '').trim().toLowerCase()
  if (url) return `url:${url}`
  return `tcl:${(job.title || '').toLowerCase()}|${(job.company || '').toLowerCase()}|${(job.location || '').toLowerCase()}`
}

// Stamps and placeholders a record gets without the owner having done anything.
const BOOKKEEPING_FIELDS = new Set(['updatedAt', 'lastUpdated', 'generatedAt'])

function hasContent(value) {
  if (Array.isArray(value)) return value.some(hasContent)
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, inner]) => !BOOKKEEPING_FIELDS.has(key) && hasContent(inner))
  }
  return value !== null && value !== undefined && value !== '' && value !== false
}

/** Whether the row holds something only the owner's work put there: "Keep this ad", a triage status, AI insights, tailored assets, outreach or legacy tracking. */
export function hasUserData(job) {
  if (!job) return false
  const { status: outreachStatus, ...outreach } = job.outreach || {}
  return job.keptByUser === true
    || Boolean(job.status && job.status !== 'new')
    || hasContent(job.aiInsights)
    || hasContent(job.tailoredAssets)
    || (Boolean(outreachStatus) && outreachStatus !== 'none')
    || hasContent(outreach)
    || hasContent(job.applicationTracking)
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
      kept: job.keptByUser === true ? { keptByUser: true, keptAt: job.keptAt } : null,
      manual: Object.fromEntries([...MANUAL_FIELDS, ...(job.manualEntry ? MANUAL_ONLY_FIELDS : [])].filter((f) => f in job).map((f) => [f, job[f]])),
    }
    preservedByKey.set(jobMatchKey(job), entry)
    if (job.jobId) preservedById.set(job.jobId, entry)
  }

  return incomingJobs.map((job) => {
    const key = jobMatchKey(job)
    const preserved = preservedById.get(job.jobId) ?? preservedByKey.get(key)
    // A row in the file is in current results, whatever a copy of it said.
    const { offList: _inResults, ...fresh } = job
    return {
      ...fresh,
      ...preserved?.manual,
      ...preserved?.kept, // the owner kept this ad, whatever later runs say: it must outlast its next absence too
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
  // posting): the hand-entered one stays, so the list has one row for it. The address is the identity URL, which keeps
  // ?gh_jid= style parameters: sibling postings of one board are different jobs and are never dropped here.
  const manualAt = new Map(prior.filter((job) => job.manualEntry).map((job) => [identityJobUrl(job.jobUrl), job.jobId]).filter(([url]) => url))
  const incoming = jobs.filter((job) => {
    const owner = manualAt.get(identityJobUrl(job.jobUrl))
    return !owner || owner === job.jobId
  })
  const merged = mergeStatusOnImport(prior, incoming)
  // A hand-entered job the file lacks (saved while the server was away) is not dropped by a re-import.
  const present = new Set(merged.map((job) => job.jobId))
  const kept = prior.filter((job) => job.manualEntry && !present.has(job.jobId))
  // Discovery finds ads and never deletes what the owner did: a row the file lacks stays, marked, if it holds their work.
  // "In the file" is every row of the file, with the id and address the merge matches on.
  const fileIds = new Set(jobs.map((job) => job.jobId))
  const fileKeys = new Set(jobs.map(jobMatchKey))
  const offList = prior
    .filter((job) => !job.manualEntry && !fileIds.has(job.jobId) && !fileKeys.has(jobMatchKey(job)) && hasUserData(job))
    .map((job) => ({ ...job, offList: true }))
  return {
    meta: meta || existingState?.meta || null,
    jobs: [...merged, ...kept, ...offList],
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
