/**
 * Owner state of jobs on the server (Wave 6 j; the narrow first part of STEP5_SERVER_MASTER_PLAN 2.3).
 *
 *   data/jobs/job-state.json   { version: 1, updatedAt, jobs: { "<matchKey>": { jobId, status, statusAt, keep } } }
 *
 * Only `status` (new | saved | rejected) and `keep` live here. "Applied" is never stored: it is derived from the application store.
 * The pipeline never reads or writes this file. The version of the file is the sha256 of its bytes (`none` when it does not exist);
 * a write that names a `baseSha256` which is no longer current answers 409 `stale`.
 *
 * Moving the browser's statuses and Keep flags here is a union and never automatic: export the browser state, preview (writes
 * nothing), confirm with the preview's hash, backup first, then write. An entry already on the server always wins and nothing is deleted.
 * Rows carry ids, a match key and flags only: no title, company, text, note or contact.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, copyToNewFile, replaceFileAtomic } from './atomic-file.js'
import { readRawBody, MAX_LARGE_BODY_BYTES } from './read-body.js'

const STATE_VERSION = 1
export const STATE_STATUSES = ['new', 'saved', 'rejected']
const BROWSER_STATUSES = [...STATE_STATUSES, 'applied_manually']
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/
const MATCH_KEY = /^(url|tcl):.{1,600}$/s
const MAX_ROWS = 50_000

export class StateError extends Error {
  constructor(status, message, extra = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

export function statePaths(root) {
  return { file: path.join(root, 'data/jobs/job-state.json'), backups: path.join(root, 'data/backups') }
}

const sha256 = (data) => crypto.createHash('sha256').update(data).digest('hex')

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

const locks = new Map()
function withLock(root, fn) {
  const key = statePaths(root).file
  const run = (locks.get(key) ?? Promise.resolve()).then(fn)
  locks.set(key, run.catch(() => {}))
  return run
}

export const emptyState = () => ({ version: STATE_VERSION, updatedAt: null, jobs: {} })

/** A missing file is empty. An unreadable or unknown one throws, so nothing is ever written over it. */
export function loadState(root) {
  const { file } = statePaths(root)
  if (!fs.existsSync(file)) return { doc: emptyState(), sha256: 'none' }
  const bytes = fs.readFileSync(file)
  let doc
  try {
    doc = JSON.parse(bytes.toString('utf-8'))
  } catch (e) {
    throw new StateError(500, `job-state.json is unreadable, refusing to touch it: ${e.message}`)
  }
  if (doc?.version !== STATE_VERSION || typeof doc.jobs !== 'object' || doc.jobs === null) {
    throw new StateError(500, 'job-state.json has an unknown shape, refusing to touch it')
  }
  return { doc, sha256: sha256(bytes) }
}

function writeState(root, doc) {
  const { file } = statePaths(root)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const text = `${JSON.stringify(doc, null, 2)}\n`
  replaceFileAtomic(file, text, { mode: PRIVATE_FILE_MODE })
  return sha256(text)
}

/** Throws unless `next` holds every entry of `prev` unchanged (entries may only be added). */
export function assertUnionOnly(prev, next) {
  for (const [key, entry] of Object.entries(prev.jobs)) {
    if (!next.jobs[key] || canonicalJson(next.jobs[key]) !== canonicalJson(entry)) {
      throw new StateError(500, 'union violation: an existing entry would change or disappear')
    }
  }
}

// --- one entry --------------------------------------------------------------------------------

/** Merge `patch` (status and/or keep) into one entry under the lock. A stale `baseSha256` answers 409 and writes nothing. */
export function patchState(root, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const { key, jobId, patch, baseSha256 } = body ?? {}
    if (typeof key !== 'string' || !MATCH_KEY.test(key)) throw new StateError(400, 'key must be a job match key')
    if (typeof jobId !== 'string' || !JOB_ID.test(jobId)) throw new StateError(400, 'jobId is not valid')
    if (!patch || typeof patch !== 'object' || Array.isArray(patch)) throw new StateError(400, 'patch must be an object')
    const unknown = Object.keys(patch).filter((f) => f !== 'status' && f !== 'keep')
    if (unknown.length || Object.keys(patch).length === 0) throw new StateError(400, 'patch may hold only status and keep')
    if ('status' in patch && !STATE_STATUSES.includes(patch.status)) {
      throw new StateError(400, patch.status === 'applied_manually' ? 'Applied is recorded in the application tracker, not as a status' : 'status is not valid')
    }
    if ('keep' in patch && typeof patch.keep !== 'boolean') throw new StateError(400, 'keep must be true or false')

    const { doc, sha256: current } = loadState(root)
    if (baseSha256 !== undefined && baseSha256 !== current) {
      throw new StateError(409, 'job-state.json changed since it was read', { code: 'stale', current: { sha256: current } })
    }
    const at = now().toISOString()
    const before = doc.jobs[key]
    const entry = { jobId, status: before?.status ?? 'new', statusAt: before?.statusAt ?? null, keep: before?.keep ?? false }
    if ('status' in patch && patch.status !== entry.status) { entry.status = patch.status; entry.statusAt = at }
    if ('keep' in patch) entry.keep = patch.keep
    if (before && canonicalJson(before) === canonicalJson(entry)) return { status: 200, entry, sha256: current, changed: false }
    const next = { ...doc, updatedAt: at, jobs: { ...doc.jobs, [key]: entry } }
    return { status: 200, entry, sha256: writeState(root, next), changed: true }
  })
}

/**
 * Removes every entry of one job. Used only when a hand-entered job is deleted: this is the one place the "entries are only
 * added" rule does not apply, and it touches only entries whose jobId is the deleted job's. A missing file writes nothing.
 */
export function removeJobStateEntries(root, jobId) {
  return withLock(root, () => {
    const { doc } = loadState(root)
    const keys = Object.keys(doc.jobs).filter((k) => doc.jobs[k]?.jobId === jobId)
    if (!keys.length) return { removed: 0 }
    const jobs = { ...doc.jobs }
    for (const k of keys) delete jobs[k]
    writeState(root, { ...doc, updatedAt: new Date().toISOString(), jobs })
    return { removed: keys.length }
  })
}

// --- the browser's state: export, preview, import ----------------------------------------------

/** The rows a browser sends, reduced to ids and flags. Invalid ones are counted, never stored. */
export function sanitizeRows(rows) {
  if (!Array.isArray(rows)) throw new StateError(400, 'rows must be a list')
  if (rows.length > MAX_ROWS) throw new StateError(413, 'too many rows')
  const clean = []
  let invalid = 0
  for (const row of rows) {
    const ok = row && typeof row === 'object' && JOB_ID.test(row.jobId ?? '') && MATCH_KEY.test(row.key ?? '')
      && BROWSER_STATUSES.includes(row.status ?? 'new') && typeof (row.keep ?? false) === 'boolean'
    if (!ok) { invalid += 1; continue }
    clean.push({ jobId: row.jobId, key: row.key, status: row.status ?? 'new', keep: row.keep ?? false, offList: row.offList === true })
  }
  clean.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
  return { rows: clean, invalid }
}

const stamp = (date) => date.toISOString().replace(/[-:]/g, '').replace(/\..*/, '').replace('T', '-')

/** Write the browser's statuses and Keep flags to data/backups/browser-state-<ts>.json (600). Touches nothing else. */
export function exportBrowserState(root, body, { now = () => new Date() } = {}) {
  const { rows, invalid } = sanitizeRows(body?.rows)
  const { backups } = statePaths(root)
  fs.mkdirSync(backups, { recursive: true, mode: PRIVATE_DIR_MODE })
  const file = path.join(backups, `browser-state-${stamp(now())}.json`)
  if (fs.existsSync(file)) throw new StateError(409, 'an export with this timestamp exists; try again in a second')
  const doc = { version: 1, createdAt: now().toISOString(), rows }
  replaceFileAtomic(file, `${JSON.stringify(doc, null, 2)}\n`, { mode: PRIVATE_FILE_MODE })
  return { status: 200, path: path.relative(root, file), rows: rows.length, invalid, sha256: sha256(fs.readFileSync(file)) }
}

/** The union plan. Pure. Server entries win; nothing is deleted; an applied row is the tracker's business, not this file's. */
export function planImport(rows, state) {
  const counts = { scanned: rows.length, ignored: 0, appliedInBrowser: 0, toAdd: 0, alreadyThere: 0, conflicts: 0 }
  const additions = {}
  const conflicts = []
  const seen = new Set()
  for (const row of rows) {
    if (seen.has(row.key)) { counts.ignored += 1; continue }
    seen.add(row.key)
    const status = row.status === 'applied_manually' ? 'new' : row.status
    if (row.status === 'applied_manually') counts.appliedInBrowser += 1
    if (status === 'new' && !row.keep) { counts.ignored += 1; continue }
    const have = state.jobs[row.key]
    if (!have) {
      counts.toAdd += 1
      additions[row.key] = { jobId: row.jobId, status, statusAt: null, keep: row.keep }
    } else if (have.status === status && have.keep === row.keep) {
      counts.alreadyThere += 1
    } else {
      counts.conflicts += 1
      const fields = [have.status !== status && 'status', have.keep !== row.keep && 'keep'].filter(Boolean)
      conflicts.push({ jobId: row.jobId, fields, kept: 'server' })
    }
  }
  return { counts, additions, conflicts }
}

const previewShaOf = (rows, stateSha) => sha256(canonicalJson({ rows, stateSha }))

export function previewImport(root, body) {
  const { rows, invalid } = sanitizeRows(body?.rows)
  const { doc, sha256: stateSha } = loadState(root)
  const plan = planImport(rows, doc)
  return { status: 200, dryRun: true, previewSha: previewShaOf(rows, stateSha), invalid, counts: plan.counts, conflicts: plan.conflicts }
}

/** Apply a reviewed preview: refused (409) without `confirm: true` and the preview's hash. Backup first; a failed backup writes nothing. */
export function applyImport(root, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const { rows } = sanitizeRows(body?.rows)
    const { doc, sha256: stateSha } = loadState(root)
    if (body?.confirm !== true) throw new StateError(409, 'The import needs { "confirm": true }')
    const previewSha = previewShaOf(rows, stateSha)
    if (body.previewSha !== previewSha) throw new StateError(409, 'previewSha does not match the rows and the current server state; run the preview again', { previewSha })
    const plan = planImport(rows, doc)
    if (plan.counts.toAdd === 0) return { status: 200, dryRun: false, changed: false, counts: plan.counts, conflicts: plan.conflicts, sha256: stateSha }

    const { backups, file } = statePaths(root)
    const dir = path.join(backups, `job-state-${stamp(now())}`)
    try {
      fs.mkdirSync(backups, { recursive: true, mode: PRIVATE_DIR_MODE })
      fs.mkdirSync(dir, { mode: PRIVATE_DIR_MODE })
      if (fs.existsSync(file)) copyToNewFile(file, path.join(dir, 'job-state.json'), PRIVATE_FILE_MODE)
      replaceFileAtomic(path.join(dir, 'browser-state.json'), `${JSON.stringify({ version: 1, rows }, null, 2)}\n`, { mode: PRIVATE_FILE_MODE })
    } catch (e) {
      throw new StateError(500, `Backup failed, nothing was imported: ${e.message}`)
    }
    const at = now().toISOString()
    const next = { ...doc, updatedAt: at, jobs: { ...doc.jobs, ...plan.additions } }
    assertUnionOnly(doc, next)
    const sha = writeState(root, next)
    return { status: 200, dryRun: false, changed: true, backupPath: path.relative(root, dir), counts: plan.counts, conflicts: plan.conflicts, sha256: sha }
  })
}

/**
 * A restored `data/jobs/job-state.json` never replaces the live one: its entries are added where the key is missing, and an entry
 * already on the server stays as it is. Returns { added, kept } or { refused } when the archived file is not a job-state document.
 */
export function mergeStateFromBackup(root, bytes, { now = () => new Date() } = {}) {
  let archived
  try {
    archived = JSON.parse(Buffer.from(bytes).toString('utf-8'))
  } catch {
    return { refused: 'not valid JSON' }
  }
  if (archived?.version !== STATE_VERSION || typeof archived.jobs !== 'object' || archived.jobs === null) return { refused: 'unknown shape' }
  const { doc } = loadState(root)
  const additions = {}
  let kept = 0
  for (const [key, entry] of Object.entries(archived.jobs)) {
    if (doc.jobs[key]) { kept += 1; continue }
    if (!MATCH_KEY.test(key) || !JOB_ID.test(entry?.jobId ?? '') || !STATE_STATUSES.includes(entry.status) || typeof entry.keep !== 'boolean') continue
    additions[key] = { jobId: entry.jobId, status: entry.status, statusAt: typeof entry.statusAt === 'string' ? entry.statusAt : null, keep: entry.keep }
  }
  const added = Object.keys(additions).length
  if (added) {
    const next = { ...doc, updatedAt: now().toISOString(), jobs: { ...doc.jobs, ...additions } }
    assertUnionOnly(doc, next)
    writeState(root, next)
  }
  return { added, kept }
}

export const isJobStateBackupEntry = (name) => name === 'data/jobs/job-state.json'

// --- routes ------------------------------------------------------------------------------------

function sendJson(res, status, data) {
  if (res.writableEnded) return
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(data))
}

async function readBody(req, res) {
  const raw = (await readRawBody(req, res, { limit: MAX_LARGE_BODY_BYTES })).toString('utf-8')
  try {
    return raw ? JSON.parse(raw) : {}
  } catch {
    throw new StateError(400, 'Body is not valid JSON')
  }
}

const ROUTES = {
  'GET /api/jobs/state': (_req, _res, { root }) => ({ status: 200, ...loadState(root) }),
  'POST /api/jobs/state': (body, { root, now }) => patchState(root, body, { now }),
  'POST /api/jobs/state/browser-export': (body, { root, now }) => exportBrowserState(root, body, { now }),
  'POST /api/jobs/state/import/preview': (body, { root }) => previewImport(root, body),
  'POST /api/jobs/state/import': (body, { root, now }) => applyImport(root, body, { now }),
}

/** Handle a request under /api/jobs/state. Returns false for any other URL. */
export async function handleJobStateRequest(req, res, url, { root, now } = {}) {
  if (url !== '/api/jobs/state' && !url.startsWith('/api/jobs/state/')) return false
  const handler = ROUTES[`${req.method} ${url}`]
  if (!handler) {
    sendJson(res, 404, { error: 'API route not found' })
    return true
  }
  try {
    const body = req.method === 'GET' ? null : await readBody(req, res)
    const result = await (req.method === 'GET' ? handler(null, res, { root }) : handler(body, { root, ...(now ? { now } : {}) }))
    const { status, ...rest } = result
    sendJson(res, status, rest)
  } catch (e) {
    sendJson(res, e instanceof StateError ? e.status : 500, { error: e.message, ...(e.extra ?? {}) })
  }
  return true
}
