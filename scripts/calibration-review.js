/**
 * The temporary calibration review (P1 Stage A): the owner confirms or changes an AI pre-label for each ad of a sample.
 *
 *   data/calibration/stage-a/review-items.json   the sample: id, title, company, location, site, link, description only
 *   data/calibration/stage-a/ai-proposals.json   the AI's proposals (written by python/calibration/prelabel.py); read only
 *   data/calibration/stage-a/ran-labels.json     { version: 1, revision, updatedAt, labels: { "<jobId>": { ... } } }; the only file written here
 *
 * The owner's confirmed labels are the ground truth; a proposal is only a suggestion. Nothing about the system's own score, label, cap or
 * engine output exists in these files, so none can be returned. Routes: GET /api/calibration/review, PUT /api/calibration/labels.
 */
import fs from 'node:fs'
import path from 'node:path'
import { PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'
import { readRawBody } from './read-body.js'

export const LABELS_VERSION = 1
export const FUNCTION_FIT = ['yes', 'partial', 'no']
export const HARD_REQUIREMENTS = ['yes', 'partial', 'no', 'unknown']
export const OVERALL = [0, 1, 2, 3]
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/
const BODY_LIMIT = 4 * 1024
const BODY_KEYS = ['jobId', 'functionFit', 'hardRequirements', 'overall']

export class ReviewError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export function reviewPaths(root) {
  const dir = path.join(root, 'data/calibration/stage-a')
  return { dir, items: path.join(dir, 'review-items.json'), proposals: path.join(dir, 'ai-proposals.json'), labels: path.join(dir, 'ran-labels.json') }
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

function loadItems(root) {
  const doc = readJson(reviewPaths(root).items, null)
  if (!doc || !Array.isArray(doc.items)) throw new ReviewError(404, 'There is no calibration sample on this server')
  return doc.items
}

function loadLabels(root) {
  const doc = readJson(reviewPaths(root).labels, { version: LABELS_VERSION, revision: 0, updatedAt: null, labels: {} })
  if (doc.version !== LABELS_VERSION || typeof doc.labels !== 'object' || doc.labels === null) {
    throw new ReviewError(500, 'The labels file has an unknown format')
  }
  return doc
}

const PROPOSAL_FIELDS = ['functionFit', 'hardRequirements', 'overall', 'reason', 'confidence', 'missingInformation']

/** Only the displayable part of a proposal; an invalid or absent one is null (the card then asks for all three judgments). */
function publicProposal(entry) {
  if (!entry || entry.status !== 'ok') return null
  return Object.fromEntries(PROPOSAL_FIELDS.map((k) => [k, entry[k] ?? null]))
}

const progressOf = (items, labels) => ({ total: items.length, reviewed: items.filter((i) => labels[i.jobId]).length })

export function getReview(root) {
  const items = loadItems(root)
  const proposals = readJson(reviewPaths(root).proposals, { proposals: {} }).proposals || {}
  const doc = loadLabels(root)
  return {
    status: 200,
    revision: doc.revision,
    progress: progressOf(items, doc.labels),
    items: items.map((i) => ({
      jobId: i.jobId, title: i.title, company: i.company, location: i.location, site: i.site, jobUrl: i.jobUrl,
      description: i.description, proposal: publicProposal(proposals[i.jobId]), label: doc.labels[i.jobId] ?? null,
    })),
  }
}

function validate(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new ReviewError(400, 'Body must be an object')
  const unknown = Object.keys(body).filter((k) => !BODY_KEYS.includes(k))
  if (unknown.length) throw new ReviewError(400, `Unknown field: ${unknown[0]}`)
  if (typeof body.jobId !== 'string' || !JOB_ID.test(body.jobId)) throw new ReviewError(400, 'jobId is not valid')
  if (!FUNCTION_FIT.includes(body.functionFit)) throw new ReviewError(400, `functionFit must be one of ${FUNCTION_FIT.join(', ')}`)
  if (!HARD_REQUIREMENTS.includes(body.hardRequirements)) throw new ReviewError(400, `hardRequirements must be one of ${HARD_REQUIREMENTS.join(', ')}`)
  if (!OVERALL.includes(body.overall)) throw new ReviewError(400, 'overall must be 0, 1, 2 or 3')
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
 * Saves the owner's three judgments for one ad of the sample. `source` is worked out here, not taken from the browser:
 * "confirmed" when all three equal the AI proposal, "changed" when any differs, "manual" when there was no proposal.
 */
export async function saveLabel(root, body, { now = () => new Date() } = {}) {
  const input = validate(body)
  return serialised(async () => {
    const items = loadItems(root)
    if (!items.some((i) => i.jobId === input.jobId)) throw new ReviewError(404, 'That ad is not in the sample')
    const proposals = readJson(reviewPaths(root).proposals, { proposals: {} }).proposals || {}
    const proposal = publicProposal(proposals[input.jobId])
    const same = proposal && proposal.functionFit === input.functionFit
      && proposal.hardRequirements === input.hardRequirements && proposal.overall === input.overall
    const doc = loadLabels(root)
    const label = {
      jobId: input.jobId, functionFit: input.functionFit, hardRequirements: input.hardRequirements, overall: input.overall,
      source: !proposal ? 'manual' : same ? 'confirmed' : 'changed', savedAt: now().toISOString(),
    }
    const next = { version: LABELS_VERSION, revision: doc.revision + 1, updatedAt: label.savedAt, labels: { ...doc.labels, [input.jobId]: label } }
    replaceFileAtomic(reviewPaths(root).labels, JSON.stringify(next, null, 2), { mode: PRIVATE_FILE_MODE })
    return { status: 200, label, revision: next.revision, progress: progressOf(items, next.labels) }
  })
}

function sendJson(res, status, data) {
  if (res.writableEnded) return
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(data))
}

/** Handles /api/calibration/*. Returns false for any other URL. */
export async function handleCalibrationRequest(req, res, url, { root, now } = {}) {
  if (!url.startsWith('/api/calibration/')) return false
  try {
    let result
    if (req.method === 'GET' && url === '/api/calibration/review') {
      result = getReview(root)
    } else if (req.method === 'PUT' && url === '/api/calibration/labels') {
      const raw = (await readRawBody(req, res, { limit: BODY_LIMIT })).toString('utf-8')
      let body
      try {
        body = raw ? JSON.parse(raw) : {}
      } catch {
        throw new ReviewError(400, 'Body is not valid JSON')
      }
      result = await saveLabel(root, body, now ? { now } : undefined)
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
