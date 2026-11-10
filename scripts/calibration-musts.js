/**
 * The must-have precision review (P1 Stage A, step 8): the owner judges single requirements the engine's input marked.
 *
 *   data/calibration/stage-a/must-sample.json      the sample (python/calibration/must_sample.py); each item also holds the engine's
 *                                                  verdict, its class, its mode and whether it is a probe. Read only here.
 *   data/calibration/stage-a/review-items.json     ad titles, companies and text for context; read only
 *   data/calibration/stage-a/ran-must-labels.json  { version: 1, revision, updatedAt, labels: { "<itemId>": { ... } } }; the only file written here
 *
 * Blind first. GET returns the requirement, its kind and the ad's own words, and never the engine's verdict, the model's importance,
 * the item's class or mode, or whether it is a probe. The verdict is returned only with a saved answer (PUT, and GET for an item already
 * answered). The first answer is kept as it was given; a later change is stored next to it and flagged, so the report can use the blind one.
 * Routes: GET /api/calibration/musts, PUT /api/calibration/musts/labels. ran-labels.json is never opened.
 */
import fs from 'node:fs'
import path from 'node:path'
import { PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'
import { readRawBody } from './read-body.js'
import { ReviewError } from './calibration-review.js'

export const MUST_LABELS_VERSION = 1
export const IS_MUST = ['yes', 'nice', 'no']
export const MEETS = ['yes', 'partial', 'no', 'unknown']
const ITEM_ID = /^i[0-9]{2,3}$/
const BODY_LIMIT = 2 * 1024
const BODY_KEYS = ['itemId', 'isMust', 'meets']

export function mustPaths(root) {
  const dir = path.join(root, 'data/calibration/stage-a')
  return { dir, sample: path.join(dir, 'must-sample.json'), ads: path.join(dir, 'review-items.json'), labels: path.join(dir, 'ran-must-labels.json') }
}

/** A missing file is `fallback`; an unreadable or malformed one throws, so nothing is written over it. */
function readJson(file, fallback) {
  let text
  try {
    text = fs.readFileSync(file, 'utf-8')
  } catch (e) {
    if (e.code === 'ENOENT') return fallback
    throw new ReviewError(500, 'A calibration file cannot be read')
  }
  try {
    return JSON.parse(text)
  } catch {
    throw new ReviewError(500, 'A calibration file is not valid JSON')
  }
}

function loadSample(root) {
  const doc = readJson(mustPaths(root).sample, null)
  if (!doc || !Array.isArray(doc.items)) throw new ReviewError(404, 'There is no must-have sample on this server')
  return doc.items
}

function loadLabels(root) {
  const doc = readJson(mustPaths(root).labels, { version: MUST_LABELS_VERSION, revision: 0, updatedAt: null, labels: {} })
  if (doc.version !== MUST_LABELS_VERSION || typeof doc.labels !== 'object' || doc.labels === null) {
    throw new ReviewError(500, 'The must labels file has an unknown format')
  }
  return doc
}

/** What the engine said about an item: shown only next to a saved answer. */
const revealOf = (item) => ({
  status: item.verdict?.status ?? null, strength: item.verdict?.strength ?? null, evidenceQuote: item.verdict?.evidenceQuote ?? null,
})

const progressOf = (items, labels) => ({ total: items.length, answered: items.filter((i) => labels[i.itemId]).length })

export function getMusts(root) {
  const items = loadSample(root)
  const doc = loadLabels(root)
  const adRows = readJson(mustPaths(root).ads, { items: [] }).items || []
  const wanted = new Set(items.map((i) => i.jobId))
  const ads = Object.fromEntries(adRows.filter((a) => wanted.has(a.jobId)).map((a) => [a.jobId, {
    title: a.title, company: a.company, jobUrl: a.jobUrl, description: a.description,
  }]))
  return {
    status: 200,
    revision: doc.revision,
    progress: progressOf(items, doc.labels),
    ads,
    items: items.map((i) => ({
      itemId: i.itemId, jobId: i.jobId, kind: i.kind, text: i.text, postingQuote: i.postingQuote ?? null,
      label: doc.labels[i.itemId] ?? null, reveal: doc.labels[i.itemId] ? revealOf(i) : null,
    })),
  }
}

function validate(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new ReviewError(400, 'Body must be an object')
  const unknown = Object.keys(body).filter((k) => !BODY_KEYS.includes(k))
  if (unknown.length) throw new ReviewError(400, `Unknown field: ${unknown[0]}`)
  if (typeof body.itemId !== 'string' || !ITEM_ID.test(body.itemId)) throw new ReviewError(400, 'itemId is not valid')
  if (!IS_MUST.includes(body.isMust)) throw new ReviewError(400, `isMust must be one of ${IS_MUST.join(', ')}`)
  if (!MEETS.includes(body.meets)) throw new ReviewError(400, `meets must be one of ${MEETS.join(', ')}`)
  return body
}

let queue = Promise.resolve()
/** Writes are serialised, so two quick saves from one screen never lose each other. */
function serialised(fn) {
  const run = queue.then(fn)
  queue = run.catch(() => {})
  return run
}

/**
 * Saves the owner's two answers for one item and returns the engine's verdict with them. The first answer is kept as `first`
 * for good; a later save replaces `final` and sets `changedAfterReveal` when it differs from the first.
 */
export async function saveMust(root, body, { now = () => new Date() } = {}) {
  const input = validate(body)
  return serialised(async () => {
    const items = loadSample(root)
    const item = items.find((i) => i.itemId === input.itemId)
    if (!item) throw new ReviewError(404, 'That item is not in the sample')
    const doc = loadLabels(root)
    const at = now().toISOString()
    const answer = { isMust: input.isMust, meets: input.meets, savedAt: at }
    const before = doc.labels[input.itemId]
    const first = before ? before.first : answer
    const label = {
      itemId: input.itemId, first, final: answer, changedAfterReveal: first.isMust !== answer.isMust || first.meets !== answer.meets,
    }
    const next = { version: MUST_LABELS_VERSION, revision: doc.revision + 1, updatedAt: at, labels: { ...doc.labels, [input.itemId]: label } }
    replaceFileAtomic(mustPaths(root).labels, JSON.stringify(next, null, 2), { mode: PRIVATE_FILE_MODE })
    return { status: 200, label, reveal: revealOf(item), revision: next.revision, progress: progressOf(items, next.labels) }
  })
}

function sendJson(res, status, data) {
  if (res.writableEnded) return
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(data))
}

/** Handles /api/calibration/musts*. Returns false for any other URL. */
export async function handleMustRequest(req, res, url, { root, now } = {}) {
  if (url !== '/api/calibration/musts' && !url.startsWith('/api/calibration/musts/')) return false
  try {
    let result
    if (req.method === 'GET' && url === '/api/calibration/musts') {
      result = getMusts(root)
    } else if (req.method === 'PUT' && url === '/api/calibration/musts/labels') {
      const raw = (await readRawBody(req, res, { limit: BODY_LIMIT })).toString('utf-8')
      let body
      try {
        body = raw ? JSON.parse(raw) : {}
      } catch {
        throw new ReviewError(400, 'Body is not valid JSON')
      }
      result = await saveMust(root, body, now ? { now } : undefined)
    } else {
      throw new ReviewError(404, 'API route not found')
    }
    const { status, ...rest } = result
    sendJson(res, status, rest)
  } catch (e) {
    sendJson(res, e instanceof ReviewError ? e.status : 500, { error: e instanceof ReviewError ? e.message : 'Calibration request failed' })
  }
  return true
}
