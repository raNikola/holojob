/**
 * The browser's side of data/jobs/job-state.json (Wave 6 j; scripts/job-state-store.js is the master).
 *
 * Reading never writes: the server's statuses and Keep flags are laid over the job list for display (`withServerState`), and
 * nothing is written to the browser by a load. A status or Keep flag that exists only in this browser stays visible, and `pendingRows`
 * counts it until the owner exports the browser state and confirms the import (Settings). A status change is written to the
 * server first; a failed write changes nothing.
 */

import { ensureApiAvailable } from '../../utils/apiAvailability.js'
import { jobMatchKey } from './jobStorage.js'

export class JobStateError extends Error {
  constructor(status, message, extra = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

const IDLE = { status: 'idle', doc: null, sha256: null, error: null }
let state = IDLE
const listeners = new Set()
let inflight = null

export const getJobState = () => state
export function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
function publish(next) {
  state = next
  for (const listener of listeners) listener()
}
/** For tests. */
export function resetJobState() {
  state = IDLE
  inflight = null
}

async function request(method, url, body) {
  if (!(await ensureApiAvailable())) throw new JobStateError(0, 'Job statuses need the local API server')
  const res = await globalThis.fetch(url, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    const { error, ...extra } = payload
    throw new JobStateError(res.status, error || `Request failed (${res.status})`, extra)
  }
  return payload
}

export function refreshJobState() {
  if (inflight) return inflight
  if (state.status !== 'ready') publish({ ...state, status: 'loading', error: null })
  inflight = (async () => {
    try {
      const { doc, sha256 } = await request('GET', '/api/jobs/state')
      if (!(state.status === 'ready' && state.sha256 === sha256)) publish({ status: 'ready', doc, sha256, error: null })
    } catch (e) {
      publish({ ...state, status: 'error', error: e.message })
    } finally {
      inflight = null
    }
    return state
  })()
  return inflight
}

// --- pure ---------------------------------------------------------------------------------------

/** The rows sent to the server: ids and flags only (never a title, note or text). */
export function rowsFromJobs(jobs) {
  return (jobs ?? [])
    .filter((job) => job?.jobId)
    .map((job) => ({ jobId: job.jobId, key: jobMatchKey(job), status: job.status || 'new', keep: job.keptByUser === true, offList: job.offList === true }))
}

/** The jobs as shown: the server's status and Keep win where it has an entry; every other row keeps its local values. Saves nothing. */
export function withServerState(jobs, doc) {
  if (!doc?.jobs) return jobs
  return jobs.map((job) => {
    const entry = doc.jobs[jobMatchKey(job)]
    if (!entry) return job
    return { ...job, status: entry.status, ...(entry.keep ? { keptByUser: true } : {}) }
  })
}

/** Browser rows with a status or Keep the server does not hold (or holds differently): what an import would add or contest. */
export function pendingRows(jobs, doc) {
  if (!doc?.jobs) return []
  return rowsFromJobs(jobs).filter((row) => {
    const acted = row.keep || (row.status !== 'new')
    if (!acted) return false
    const entry = doc.jobs[row.key]
    if (!entry) return true
    const status = row.status === 'applied_manually' ? 'new' : row.status
    return entry.status !== status || entry.keep !== row.keep
  })
}

export const PENDING_NOTICE = (count) => `${count} status${count === 1 ? '' : 'es'} or Keep flag${count === 1 ? ' is' : 's are'} only in this browser, not on the server yet. They stay visible here. Settings > Application tracking > Job statuses: export them, then import.`

// --- writes -------------------------------------------------------------------------------------

/**
 * Write a status (or Keep) change to the server. Resolves after the server's answer and updates the cache; rejects, changing
 * nothing, on any failure. A stale answer (409) refreshes the cache and rejects, so the owner sees the current value.
 */
export async function writeJobState(job, patch) {
  try {
    const result = await request('POST', '/api/jobs/state', { key: jobMatchKey(job), jobId: job.jobId, patch, ...(state.sha256 ? { baseSha256: state.sha256 } : {}) })
    publish({ status: 'ready', doc: { ...(state.doc ?? { version: 1, updatedAt: null, jobs: {} }), jobs: { ...(state.doc?.jobs ?? {}), [jobMatchKey(job)]: result.entry } }, sha256: result.sha256, error: null })
    return result
  } catch (e) {
    if (e.status === 409) await refreshJobState()
    throw e
  }
}

/** Export the browser's statuses and Keep flags to a private file on the server. Writes nothing else. */
export const exportBrowserState = (jobs) => request('POST', '/api/jobs/state/browser-export', { rows: rowsFromJobs(jobs) })
export const previewJobStateImport = (jobs) => request('POST', '/api/jobs/state/import/preview', { rows: rowsFromJobs(jobs) })
export async function runJobStateImport(jobs, previewSha) {
  const result = await request('POST', '/api/jobs/state/import', { rows: rowsFromJobs(jobs), confirm: true, previewSha })
  await refreshJobState()
  return result
}
