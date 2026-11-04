/**
 * Read-only view of the job history ledger, one job at a time: GET /api/jobs/history/<jobId>.
 *
 * The ledger is about 18 MB and only the discovery run writes it (atomic rename, so a reader never sees half a file).
 * It is parsed once into an index of the fields served here and parsed again only when the file changes. This module
 * never writes, renames or creates anything: moving a corrupt ledger aside is the writer's job (`job_history.py`).
 */

import fs from 'node:fs'
import { storePaths } from './application-store.js'

const PREFIX = '/api/jobs/history/'
// The same job id the application store accepts.
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/

let cached = null
let loading = null

/** Forgets the index. For tests. */
export function resetJobHistoryCache() {
  cached = null
  loading = null
}

function buildIndex(text) {
  const data = JSON.parse(text)
  const jobs = data?.jobs
  if (!jobs || typeof jobs !== 'object' || Array.isArray(jobs)) throw new Error('Not a job history ledger')
  // A Map, so an id such as `constructor` is only ever a key. Only what the route returns is kept in memory.
  const index = new Map()
  for (const [jobId, entry] of Object.entries(jobs)) {
    if (!entry?.job || typeof entry.job !== 'object') continue
    index.set(jobId, { job: entry.job, firstSeen: entry.firstSeen ?? null, lastSeen: entry.lastSeen ?? null, closedAt: entry.closedAt ?? null, absentSince: entry.absentSince ?? null, absentRuns: entry.absentRuns ?? 0 })
  }
  return index
}

/** The index of the ledger at `file`, or null when there is no file. Throws when the file cannot be read as a ledger. */
async function ledgerIndex(file) {
  let stat
  try {
    stat = await fs.promises.stat(file)
  } catch (error) {
    if (error.code !== 'ENOENT') throw error
    cached = null
    return null
  }
  const signature = `${file}:${stat.ino}:${stat.size}:${stat.mtimeMs}`
  if (cached?.signature === signature) return cached.index
  if (loading?.signature === signature) return loading.promise
  const promise = fs.promises.readFile(file, 'utf-8').then((text) => {
    const index = buildIndex(text)
    cached = { signature, index }
    return index
  }).finally(() => {
    if (loading?.promise === promise) loading = null
  })
  loading = { signature, promise }
  return promise
}

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

function jobIdOf(url) {
  try {
    const id = decodeURIComponent(url.slice(PREFIX.length))
    return JOB_ID.test(id) ? id : null
  } catch {
    return null
  }
}

/** @returns {Promise<boolean>} true when the request was for this route. */
export async function handleJobHistoryRequest(req, res, url, { root }) {
  if (!url.startsWith(PREFIX)) return false
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET')
    send(res, 405, { error: 'Method not allowed' })
    return true
  }
  const jobId = jobIdOf(url)
  if (!jobId) {
    send(res, 400, { error: 'Invalid job id' })
    return true
  }
  let index
  try {
    index = await ledgerIndex(storePaths(root).ledger)
  } catch {
    send(res, 503, { found: false, error: 'The job history could not be read' })
    return true
  }
  const entry = index?.get(jobId)
  if (entry) send(res, 200, { found: true, jobId, ...entry })
  else send(res, 404, { found: false })
  return true
}

// --- ad texts, in bulk (S8a) --------------------------------------------------------------------------------------------------
//
// The browser's stored job list may keep a shorter copy of the rows (jobStorage.js, tiers lean and minimal). On start it asks here for the
// ad text of the rows it stored without one, in one request per 100 ids. Read-only, from the same ledger index as the route above, and
// answering only the ad text: no contact, no note, no status. An id the ledger does not hold is named in `missing`, never invented.

const TEXTS_URL = '/api/jobs/texts'
export const MAX_TEXT_IDS = 100

/** @returns {Promise<boolean>} true when the request was for this route. */
export async function handleJobTextsRequest(req, res, url, { root, readBody }) {
  if (url !== TEXTS_URL) return false
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST')
    send(res, 405, { error: 'Method not allowed' })
    return true
  }
  let body
  try {
    body = await readBody(req, res)
  } catch {
    if (!res.writableEnded) send(res, 400, { ok: false, error: 'invalid', message: 'The body must be JSON.' }) // too large: the reader has answered already
    return true
  }
  const ids = body?.jobIds
  if (!Array.isArray(ids) || ids.length === 0 || ids.length > MAX_TEXT_IDS || !ids.every((id) => typeof id === 'string' && JOB_ID.test(id))) {
    send(res, 422, { ok: false, error: 'invalid', message: `jobIds must be 1 to ${MAX_TEXT_IDS} valid job ids.` })
    return true
  }
  let index
  try {
    index = await ledgerIndex(storePaths(root).ledger)
  } catch {
    send(res, 503, { ok: false, error: 'unreadable', message: 'The job history could not be read' })
    return true
  }
  const texts = {}
  const missing = []
  for (const id of new Set(ids)) {
    const description = index?.get(id)?.job?.description
    if (typeof description === 'string' && description.trim()) texts[id] = description
    else missing.push(id)
  }
  send(res, 200, { ok: true, texts, missing })
  return true
}
