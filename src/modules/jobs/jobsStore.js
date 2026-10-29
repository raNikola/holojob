// The browser's job list as one shared store (`jobStorage.js` is the backing store for now).
//
// Writes are field-level: `patchJob(jobId, patch)` reads the latest stored record at write time and applies only
// the given fields, so a view holding an older copy cannot revert what another view changed. Every mounted view
// re-reads through `subscribe` / `useJobs` / `useStoredJob`; other tabs arrive as a `storage` event.
//
// The shape is meant to move to the server later: a patch plus an optional `baseUpdatedAt`, and a `conflict`
// result instead of a silent overwrite. Nothing here talks to the server.
import { JOBS_STORAGE_KEY, loadJobs, onJobsSaved, saveJobs } from './jobStorage.js'

/** Never part of a patch: the id names the record, `updatedAt` is stamped here, and tracking lives in the application store. */
const RESERVED = ['jobId', 'updatedAt', 'applicationTracking']

const listeners = new Set()
let snapshot = null
let patching = false
let detachStorage = null
const jobCache = new Map()

const sameJson = (a, b) => JSON.stringify(a) === JSON.stringify(b)

function emit(source) {
  snapshot = null
  listeners.forEach((listener) => listener({ source }))
}

// A save by a screen's own effect (`source: 'save'`) is told apart from a patch so a screen ignores its own echo.
onJobsSaved(() => emit(patching ? 'patch' : 'save'))

/** The stored list, parsed once until the next write. */
export function getJobsSnapshot() {
  if (!snapshot) snapshot = { jobs: loadJobs().jobs }
  return snapshot
}

/** One stored job. The same object comes back while its content is unchanged, so effects keyed on it do not rerun. */
export function getStoredJob(jobId) {
  const fresh = getJobsSnapshot().jobs.find((job) => job.jobId === jobId) ?? null
  const cached = jobCache.get(jobId)
  if (cached && fresh && sameJson(cached, fresh)) return cached
  if (fresh) jobCache.set(jobId, fresh)
  else jobCache.delete(jobId)
  return fresh
}

function attachStorageListener() {
  if (detachStorage || typeof window === 'undefined') return
  const onStorage = (event) => {
    if (event.key === null || event.key === JOBS_STORAGE_KEY) emit('storage')
  }
  window.addEventListener('storage', onStorage)
  detachStorage = () => window.removeEventListener('storage', onStorage)
}

/** `listener({ source })` runs after any write: `patch` (this store), `save` (a screen's `saveJobs`) or `storage` (another tab). */
export function subscribe(listener) {
  listeners.add(listener)
  attachStorageListener()
  return () => {
    listeners.delete(listener)
    if (!listeners.size && detachStorage) {
      detachStorage()
      detachStorage = null
    }
  }
}

/** Tells every view to re-read, for a write made outside this store. */
export function invalidateJobs() {
  emit('invalidate')
}

function withPatching(write) {
  patching = true
  try {
    write()
  } finally {
    patching = false
  }
}

/**
 * The fields of `next` that differ from `base`, the copy the caller rendered and built `next` from.
 * A field missing from `next` becomes `undefined`, which removes it.
 */
export function diffPatch(base, next) {
  const patch = {}
  for (const key of new Set([...Object.keys(base ?? {}), ...Object.keys(next ?? {})])) {
    if (RESERVED.includes(key)) continue
    if (!sameJson(base?.[key], next?.[key])) patch[key] = next?.[key]
  }
  return patch
}

/**
 * Applies `patch` to the latest stored record of `jobId`.
 * @returns {{ ok: true, job: object, changed: boolean } | { ok: false, reason: 'missing', jobId: string } | { ok: false, reason: 'conflict', current: object }}
 */
export function patchJob(jobId, patch, { baseUpdatedAt } = {}) {
  const state = loadJobs()
  const current = state.jobs.find((job) => job.jobId === jobId)
  if (!current) return { ok: false, reason: 'missing', jobId }
  if (baseUpdatedAt !== undefined && (current.updatedAt ?? null) !== baseUpdatedAt) return { ok: false, reason: 'conflict', current }

  const fields = Object.fromEntries(Object.entries(patch ?? {}).filter(([key]) => !RESERVED.includes(key)))
  if (Object.keys(fields).every((key) => sameJson(current[key], fields[key]))) return { ok: true, job: current, changed: false }

  const job = { ...current, ...fields, updatedAt: new Date().toISOString() }
  withPatching(() => saveJobs({ ...state, jobs: state.jobs.map((j) => (j.jobId === jobId ? job : j)) }))
  return { ok: true, job, changed: true }
}

/** `patchJob` with the patch worked out from the copy the caller rendered (`base`) and the object it built (`next`). */
export function patchJobFromCopy(jobId, base, next, options) {
  return patchJob(jobId, diffPatch(base, next), options)
}

/** Adds a job the stored list does not hold yet; an existing record is never replaced. */
export function addJobIfAbsent(job) {
  const state = loadJobs()
  if (state.jobs.some((j) => j.jobId === job.jobId)) return false
  withPatching(() => saveJobs({ ...state, jobs: [...state.jobs, job] }))
  return true
}

/**
 * The in-memory list of a screen, brought up to date with the stored one: a stored field wins, a field the stored
 * record lacks (the description the scored-jobs file restores) stays, and a job only the screen holds stays.
 */
export function adoptStored(memoryJobs, storedJobs) {
  const stored = new Map(storedJobs.map((job) => [job.jobId, job]))
  const merged = memoryJobs.map((job) => (stored.has(job.jobId) ? { ...job, ...stored.get(job.jobId) } : job))
  const known = new Set(memoryJobs.map((job) => job.jobId))
  return [...merged, ...storedJobs.filter((job) => !known.has(job.jobId))]
}

/** A prop copy of a job with the stored record on top, except tracking, which the screen derives from the application store. */
export function mergeLive(job, stored) {
  if (!stored) return job
  const { applicationTracking: _derived, ...rest } = stored
  return { ...job, ...rest }
}
