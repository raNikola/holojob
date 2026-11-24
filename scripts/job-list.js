/**
 * The Jobs list on the server (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2).
 *
 *   GET /api/jobs/list?mode=active|all&offset=0[&filters=JSON][&classes=a,b][&recent=1][&sort=JSON][&today=MS][&revision=R][&ids=1]
 *       -> { ok, revision, mode, offset, limit, total, rows[], nextOffset|null, counts, meta }   one page of slim rows, in the list's order;
 *          `counts` is null from the second page on (offset above 0): the first page's counts stand
 *       -> { ok, changed: true, revision }                  when `revision` is given and the data moved since: the client says "list changed, refresh"
 *       -> { ok, revision, total, ids[], selectableIds[] }  with ids=1: every matching ad, for select-all across pages
 *   POST /api/jobs/list   { mode, offset, filters, classes, recent, sort, today, revision, ids, extraRows }
 *       -> the same answers, plus `extra: { sent, notOnServer }`. `extraRows` is the browser's own rows the server's list does not hold, sent as an
 *          ALLOWLIST (src/modules/jobs/extraRows.js): added to the stored rows for this request only, never stored, never logged. A BRIDGE to be removed in P5.
 *          A field outside the allowlist, a bad id or a repeated id is a 400 that names the place; a body over the limit is a 413 that says so.
 *   POST /api/jobs/list { ..., countsOnly: true }        -> { ok, revision, mode, total, counts }: the numbers with no rows (the Dashboard's cards, the AI context's totals)
 *   POST /api/jobs/list/rows { jobIds: [...] }          -> { ok, revision, meta, rows[], missing[] }: the scored rows of these ads (with the text, without the facts), and the ids the scored list does not hold
 *       (the browser brings the rows it HOLDS up to date with the last scoring without loading the whole list)
 *   POST /api/jobs/list/context {}                      -> { ok, revision, topJobs[], skillGap[] }: what the AI context reads of the whole list (the ten best-scored open
 *       ads in full, and the missing skills of the hundred best-scored), worked out where the whole list is
 *   GET /api/jobs/list/ad?jobId=ID
 *       -> { ok, revision, row }                            the full row (description, facts) of one scored ad, opened from the list
 *
 * The rules are not here. They are `queryJobList` and the modules under it in src/modules/jobs, the same files the Jobs screen runs: this file only
 * builds the input from the server's files, checks the request and slims the rows. Nothing is written by any route here (the one thing that can write is
 * the check every job route makes first, `ensureViewCurrent`, which rebuilds a view that is behind the ledger).
 *
 * Page size and Active period: the Settings fields `jobsPageSize` and `activeWindowDays` (the AI budget settings file, read through the gate), never a number here and
 * never a request parameter. The period decides which ads the latest search did not return stay in Active; each answer says which period it used.
 * Offset and limit with a revision check, not a cursor (owner decision 2026-11-24): the revision names the files the list was made from, so a page of a list
 * that has since changed is refused instead of showing a row twice or skipping one.
 *
 * The index (the stored rows, the route's rows, the statuses, the applications) is held in memory and rebuilt when the revision changes. The revision is
 * the size and modification time of the files, so asking for it reads nothing.
 */

import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { readAiUsage } from './ai-gate.js'
import { loadSettings as loadApplicationSettings, loadStore, storePaths } from './application-store.js'
import { readAll } from './job-all-read.js'
import { loadState, statePaths } from './job-state-store.js'
import { BodyTooLargeError, MAX_JSON_BODY_BYTES, readJsonBody } from './read-body.js'
import { ViewUnrecoverable, ensureViewCurrent, viewUnrecoverableAnswer } from './view-guard.js'
import { overlayTracking } from '../src/modules/applications/trackingView.js'
import { validWindowDays } from '../src/modules/jobs/allAds.js'
import { withServerState } from '../src/modules/jobs/jobStateClient.js'
import { ExtraRowsError, applyExtraRows, checkExtraRows } from '../src/modules/jobs/extraRows.js'
import { LIST_MODES, queryJobList } from '../src/modules/jobs/jobListQuery.js'
import { FILTER_TYPES, filterValueOk } from '../src/modules/jobs/listFilters.js'
import { importJobsFromFile, slimJob } from '../src/modules/jobs/jobStorage.js'
import { isActionable } from '../src/modules/jobs/jobHistory.js'
import { onListJobs } from '../src/modules/jobs/jobFilters.js'
import { SORT_COLUMNS } from '../src/modules/jobs/jobTableModel.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const LIST_ROUTE = '/api/jobs/list'
export const AD_ROUTE = '/api/jobs/list/ad'
export const ROWS_ROUTE = '/api/jobs/list/rows'
export const CONTEXT_ROUTE = '/api/jobs/list/context'
const CONTEXT_TOP_JOBS = 10 // the AI context's own sizes (aiContextBuilder.js), not a list's page size
const CONTEXT_SKILL_GAP_JOBS = 100
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/
const MAX_FILTERS_CHARS = 4000
const MAX_CLASSES = 40

class HttpError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

// --- the request ---------------------------------------------------------------------------------------------------------------------------------

function filtersFrom(text) {
  if (text === null) return {}
  if (text.length > MAX_FILTERS_CHARS) throw new HttpError(400, 'filters is too long')
  let filters
  try { filters = JSON.parse(text) } catch { throw new HttpError(400, 'filters is not JSON') }
  return checkFilters(filters)
}

function checkFilters(filters) {
  if (!filters || typeof filters !== 'object' || Array.isArray(filters)) throw new HttpError(400, 'filters must be an object')
  for (const [key, value] of Object.entries(filters)) {
    const kind = FILTER_TYPES[key]
    if (!Object.hasOwn(FILTER_TYPES, key) || !filterValueOk(kind, value)) throw new HttpError(400, kind === undefined ? `unknown filter: ${key}` : `filter ${key} has the wrong type`)
  }
  return filters
}

function sortFrom(text) {
  if (text === null) return null
  let sort
  try { sort = JSON.parse(text) } catch { throw new HttpError(400, 'sort is not JSON') }
  return checkSort(sort)
}

function checkSort(sort) {
  if (!sort || typeof sort !== 'object' || !Object.hasOwn(SORT_COLUMNS, sort.key) || (sort.dir !== 'asc' && sort.dir !== 'desc')) {
    throw new HttpError(400, 'sort must be { key, dir } with a known column and dir asc or desc')
  }
  return { key: sort.key, dir: sort.dir }
}

const wholeNumber = (text, name) => {
  if (!/^\d{1,15}$/.test(text)) throw new HttpError(400, `${name} must be a whole number, 0 or more`)
  return Number(text)
}

/** The checked parameters of a list request. */
export function parseListRequest(params) {
  if (params.has('limit')) throw new HttpError(400, 'limit is not a parameter: the page size is the Settings field jobsPageSize')
  if (params.has('activeWindowDays')) throw new HttpError(400, 'activeWindowDays is not a parameter: the Active period is the Settings field activeWindowDays')
  const mode = params.get('mode')
  if (!LIST_MODES.includes(mode)) throw new HttpError(400, `mode must be one of ${LIST_MODES.join(', ')}`)
  const classes = (params.get('classes') ?? '').split(',').filter(Boolean)
  if (classes.length > MAX_CLASSES || classes.some((c) => c.length > 40)) throw new HttpError(400, 'classes is not valid')
  const sort = sortFrom(params.get('sort'))
  const today = params.has('today') ? wholeNumber(params.get('today'), 'today') : null
  if (sort?.key === 'deadline' && today === null) throw new HttpError(400, 'today is required to sort by deadline: it is the browser\'s day, not the server\'s')
  const flag = (name) => ['1', 'true'].includes(params.get(name) ?? '')
  return {
    mode, classes, sort, today,
    offset: params.has('offset') ? wholeNumber(params.get('offset'), 'offset') : 0,
    filters: filtersFrom(params.get('filters')),
    recent: flag('recent'),
    ids: flag('ids'),
    revision: params.get('revision'),
  }
}

/** The checked parameters of a POST body: the same as `parseListRequest`, from JSON values, plus the browser's own rows. */
export function parseListBody(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new HttpError(400, 'the request body must be an object')
  if (Object.hasOwn(body, 'limit')) throw new HttpError(400, 'limit is not a parameter: the page size is the Settings field jobsPageSize')
  if (Object.hasOwn(body, 'activeWindowDays')) throw new HttpError(400, 'activeWindowDays is not a parameter: the Active period is the Settings field activeWindowDays')
  if (!LIST_MODES.includes(body.mode)) throw new HttpError(400, `mode must be one of ${LIST_MODES.join(', ')}`)
  const whole = (value, name) => {
    if (!Number.isInteger(value) || value < 0) throw new HttpError(400, `${name} must be a whole number, 0 or more`)
    return value
  }
  const classes = body.classes ?? []
  if (!Array.isArray(classes) || classes.length > MAX_CLASSES || classes.some((c) => typeof c !== 'string' || c.length > 40)) throw new HttpError(400, 'classes is not valid')
  const sort = body.sort === undefined || body.sort === null ? null : checkSort(body.sort)
  const today = body.today === undefined || body.today === null ? null : whole(body.today, 'today')
  if (sort?.key === 'deadline' && today === null) throw new HttpError(400, 'today is required to sort by deadline: it is the browser\'s day, not the server\'s')
  for (const name of ['recent', 'ids', 'countsOnly']) if (body[name] !== undefined && typeof body[name] !== 'boolean') throw new HttpError(400, `${name} must be true or false`)
  if (body.revision !== undefined && body.revision !== null && typeof body.revision !== 'string') throw new HttpError(400, 'revision must be a string')
  let extraRows
  try { extraRows = checkExtraRows(body.extraRows) } catch (error) {
    if (error instanceof ExtraRowsError) throw new HttpError(400, error.message)
    throw error
  }
  return {
    mode: body.mode, classes, sort, today, offset: body.offset === undefined ? 0 : whole(body.offset, 'offset'),
    filters: body.filters === undefined || body.filters === null ? {} : checkFilters(body.filters),
    recent: body.recent === true, ids: body.ids === true, countsOnly: body.countsOnly === true, revision: body.revision ?? null, extraRows,
  }
}

// --- the index -----------------------------------------------------------------------------------------------------------------------------------

/** The files the list is made from. A change to any of them is a new revision. */
function sourceFiles(root) {
  const jobs = (name) => path.join(root, 'data/jobs', name)
  const apps = storePaths(root)
  // `data/ai/settings.json` is here because the page size and the Active period are Settings: a change to either makes a different list, so it is a new revision
  return [jobs('scored_jobs.json'), jobs('job_history.json'), jobs('discovered_jobs.json'), jobs('filtered_ads.json'), statePaths(root).file, apps.store, apps.settings, path.join(root, 'data/ai/settings.json')]
}

/** A name for the data as it stands now. Reads no file: only the size and the modification time of each. */
export function revisionOf(root) {
  const hash = crypto.createHash('sha1')
  for (const file of sourceFiles(root)) {
    let part = 'absent'
    try {
      const stat = fs.statSync(file)
      part = `${stat.size}:${stat.mtimeMs}`
    } catch { /* a file that is not there yet is part of the name */ }
    hash.update(`${path.basename(file)}=${part};`)
  }
  return hash.digest('hex').slice(0, 20)
}

function readScored(root) {
  const file = path.join(root, 'data/jobs/scored_jobs.json')
  if (!fs.existsSync(file)) return { meta: null, jobs: [] }
  let scored
  try { scored = JSON.parse(fs.readFileSync(file, 'utf-8')) } catch (e) { throw new HttpError(500, `scored_jobs.json is unreadable: ${e.message}`) }
  if (!scored || !Array.isArray(scored.jobs)) throw new HttpError(500, 'scored_jobs.json holds no job list')
  return scored
}

async function buildIndex({ root, python, spawnFn, revision }) {
  const answer = JSON.parse(await readAll({ root, python, spawnFn }))
  if (answer?.ok !== true || !Array.isArray(answer.rows)) throw new HttpError(500, 'the list of all ads could not be read')
  const scored = readScored(root)
  return {
    revision,
    // The rows the browser would store after an import of the scored file; the server holds no `offList` row (plan P5, orphans).
    stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
    server: answer.rows,
    meta: answer.meta ?? null,
    scoredMeta: scored.meta ?? null,
    jobStateDoc: loadState(root).doc,
    applications: { status: 'ready', store: loadStore(root), settings: loadApplicationSettings(root) },
  }
}

const caches = new Map() // root -> { revision, index, building }

async function indexFor(options) {
  const { root, ensureView, python } = options
  await ensureView({ root, python })
  const revision = revisionOf(root)
  const slot = caches.get(root) ?? {}
  if (slot.index?.revision === revision) return slot.index
  if (slot.building?.revision === revision) return slot.building.promise
  const promise = buildIndex({ ...options, revision }).then((index) => {
    caches.set(root, { index })
    return index
  }, (error) => {
    caches.set(root, { index: slot.index })
    throw error
  })
  caches.set(root, { index: slot.index, building: { revision, promise } })
  return promise
}

/** For the tests: forget what is held in memory. */
export function clearListIndex() {
  caches.clear()
}

/** The page size, from Settings through the gate. Refuses to guess when it is not a whole number of ads. */
const gateSettings = async () => (await readAiUsage())?.settings

function pageSizeOf(settings) {
  const size = settings?.jobsPageSize
  if (!Number.isInteger(size) || size < 1) throw new HttpError(500, 'The Settings field jobsPageSize is not a whole number of ads, so the list has no page size.')
  return size
}

/** The Active period, from Settings. Refuses to guess when it is not a whole number of days (1 to 365). */
function windowDaysOf(settings) {
  const days = validWindowDays(settings?.activeWindowDays)
  if (days === null) throw new HttpError(500, 'The Settings field activeWindowDays is not a whole number of days from 1 to 365, so the Active list has no period.')
  return days
}

/** The body of a POST. Over the limit it answers 413 itself, in words, and returns null: a list that would be cut short is never made. */
async function readBody(req, res) {
  try {
    return await readJsonBody(req, res, {
      limit: MAX_JSON_BODY_BYTES,
      tooLarge: {
        ok: false,
        limitBytes: MAX_JSON_BODY_BYTES,
        error: `The browser's own ads are too many to send with one list request (the limit is ${MAX_JSON_BODY_BYTES} bytes). Nothing was cut: no list was made.`,
      },
    })
  } catch (error) {
    if (error instanceof BodyTooLargeError) return null
    if (error instanceof SyntaxError) throw new HttpError(400, 'the request body is not JSON')
    throw error
  }
}

// --- the routes ----------------------------------------------------------------------------------------------------------------------------------

/** The answer to a checked request over an index (the route, and the screen tests' stand-in server, use this one function). */
export async function listAnswer(index, request, limit, now, activeWindowDays) {
  const held = new Set(index.stored.map((row) => row.jobId))
  const result = queryJobList({
    stored: applyExtraRows(index.stored, request.extraRows), server: index.server, applications: index.applications, jobStateDoc: index.jobStateDoc,
    reference: now, mode: request.mode, filters: request.filters, classes: request.classes, recent: request.recent, sort: request.sort,
    offset: request.ids || request.countsOnly ? 0 : request.offset, limit: request.ids || request.countsOnly ? 1 : limit, today: request.today ?? undefined, withIds: request.ids,
    withCounts: request.ids || request.countsOnly || request.offset === 0, // a "Show more" page (offset above 0) is rows only: the first page's counts stand
    activeWindowDays,
  })
  const extra = request.extraRows.length ? { extra: { sent: request.extraRows.length, notOnServer: request.extraRows.filter((row) => !held.has(row.jobId)).length } } : {}
  if (request.countsOnly) return { ok: true, revision: index.revision, mode: request.mode, total: result.total, counts: result.counts, activeWindowDays, ...extra }
  if (request.ids) return { ok: true, revision: index.revision, mode: request.mode, total: result.total, ids: result.ids, selectableIds: result.selectableIds, activeWindowDays, ...extra }
  const next = request.offset + result.rows.length
  return {
    ok: true, revision: index.revision, mode: request.mode, offset: request.offset, limit, activeWindowDays, total: result.total,
    rows: result.rows.map(slimJob), nextOffset: next < result.total ? next : null, counts: result.counts, meta: index.meta, ...extra,
  }
}

function adAnswer(index, jobId) {
  if (!JOB_ID.test(jobId ?? '')) throw new HttpError(400, 'jobId is not valid')
  const stored = index.stored.find((row) => row.jobId === jobId)
  if (!stored) throw new HttpError(404, 'This ad has no scored row. Its text is in the job history: GET /api/jobs/history/<jobId>.')
  const [row] = overlayTracking(withServerState([stored], index.jobStateDoc), index.applications.store, index.applications.settings)
  return { ok: true, revision: index.revision, row }
}

/**
 * @returns {Promise<boolean>} true when the request was for these routes. `python`, `spawnFn`, `ensureView`, `readPageSize`, `now` and `demoMode` are
 * for the tests and the server wiring.
 */
/** The scored rows of the named ads, slim, and the ids the scored list does not hold. */
function rowsAnswer(index, jobIds) {
  if (!Array.isArray(jobIds) || jobIds.some((id) => typeof id !== 'string' || !JOB_ID.test(id))) throw new HttpError(400, 'jobIds must be a list of ad ids')
  if (new Set(jobIds).size !== jobIds.length) throw new HttpError(400, 'jobIds repeats an id')
  const byId = new Map(index.stored.map((row) => [row.jobId, row]))
  // The ad's text stays (a stored row of a kept or off-list ad has no other copy but the ledger's); the facts and the engine's answer, which are large, do not.
  const forStorage = (row) => {
    const rest = { ...row }
    delete rest.llmFacts
    delete rest.engineShadow
    return rest
  }
  return {
    ok: true, revision: index.revision, meta: index.scoredMeta ?? null,
    rows: jobIds.filter((id) => byId.has(id)).map((id) => forStorage(byId.get(id))),
    missing: jobIds.filter((id) => !byId.has(id)),
  }
}

/** What the AI context reads of the whole list (aiContextBuilder.js): the best-scored open ads in full, and the best-scored ads' missing skills. */
function contextAnswer(index) {
  const scored = onListJobs(index.stored).filter((job) => typeof job.matchScore === 'number')
  const best = [...scored].sort((a, b) => b.matchScore - a.matchScore)
  return {
    ok: true, revision: index.revision,
    topJobs: best.filter((job) => isActionable(job)).slice(0, CONTEXT_TOP_JOBS),
    skillGap: best.slice(0, CONTEXT_SKILL_GAP_JOBS).map((job) => ({ jobId: job.jobId, matchScore: job.matchScore, missingSkills: job.missingSkills ?? [] })),
  }
}

export async function handleJobsListRequest(req, res, url, {
  root = ROOT, python = path.join(root, '.venv/bin/python'), spawnFn = spawn, ensureView = ensureViewCurrent, readPageSize = null, readWindowDays = null,
  now = Date.now, demoMode = () => false,
} = {}) {
  if (![LIST_ROUTE, AD_ROUTE, ROWS_ROUTE, CONTEXT_ROUTE].includes(url)) return false
  const allowed = url === LIST_ROUTE ? ['GET', 'POST'] : url === ROWS_ROUTE || url === CONTEXT_ROUTE ? ['POST'] : ['GET']
  if (!allowed.includes(req.method)) {
    res.setHeader('Allow', allowed.join(', '))
    send(res, 405, { error: 'Method not allowed' })
    return true
  }
  try {
    if (demoMode()) throw new HttpError(404, 'The server list is not available in demo mode.')
    if (url === ROWS_ROUTE || url === CONTEXT_ROUTE) {
      const body = await readBody(req, res)
      if (body === null) return true // over the limit: already answered with a 413 in words
      const index = await indexFor({ root, python, spawnFn, ensureView })
      send(res, 200, url === ROWS_ROUTE ? rowsAnswer(index, body?.jobIds) : contextAnswer(index))
      return true
    }
    const params = new URL(req.url, 'http://local').searchParams
    if (url === AD_ROUTE) {
      send(res, 200, adAnswer(await indexFor({ root, python, spawnFn, ensureView }), params.get('jobId')))
      return true
    }
    let request
    if (req.method === 'POST') {
      const body = await readBody(req, res)
      if (body === null) return true // over the limit: already answered with a 413 in words
      request = parseListBody(body)
    } else {
      request = { ...parseListRequest(params), extraRows: [] }
    }
    // The gate's settings are read once for a request: the page size and the Active period are Settings, and the tests give either by hand.
    let gate = null
    const settings = async () => { gate ??= await gateSettings(); return gate }
    const limit = request.ids || request.countsOnly ? null : readPageSize ? await readPageSize() : pageSizeOf(await settings())
    const windowDays = readWindowDays ? await readWindowDays() : windowDaysOf(await settings())
    const index = await indexFor({ root, python, spawnFn, ensureView })
    if (request.revision !== null && request.revision !== index.revision) {
      send(res, 200, { ok: true, changed: true, revision: index.revision })
      return true
    }
    send(res, 200, await listAnswer(index, request, limit, now(), windowDays))
  } catch (error) {
    if (error instanceof ViewUnrecoverable) send(res, 503, viewUnrecoverableAnswer(error))
    else if (error instanceof HttpError) send(res, error.status, { ok: false, error: error.message })
    else send(res, typeof error?.status === 'number' ? error.status : 500, { ok: false, error: error.message })
  }
  return true
}
