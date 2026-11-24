// The browser's own rows that the server's list does not hold, sent with a list request (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b).
//
// A BRIDGE, to be removed in P5 (owner decision 2026-11-24): until the owner overlay lives on the server, a row only this browser has (an `offList` row, a
// hand-entered job the server was never given) or a row the server holds but the owner has worked on here (notes, outreach, tailored assets, AI insights,
// legacy tracking) must still appear in the list, rank, count and page with the server's rows. So the browser names them in the request, and the server adds
// them to its stored rows for that one request. Nothing is stored on the server.
//
// What may be sent is an ALLOWLIST. A field not in it is never sent and is refused by the server; `notes`, `extraLinks`, `sourceUrl`, outreach, tailored assets,
// AI insights and a tracking object's notes and contacts are not in it, and no rule here lists what to leave out. Owner work is sent as one flag, `ownerWork`
// (what `hasUserData` says), and legacy tracking as the three values the counts read. The Jobs list shows a browser-only row from the browser's own copy
// (`listRows`, jobListClient.js), so the server needs only what filters, orders and counts read.
//
// Pure: plain data in, plain data out, nothing is written. The server and the browser import this one file.
import { hasUserData, jobMatchKey } from './jobStorage.js'
import { identityJobUrl } from './manualJob.js'

/** What a request may say about one row: the fields the list's filters, order, tiers and counts read (one list for the browser and the server). */
export const EXTRA_ROW_FIELDS = [
  'jobId', 'jobUrl', 'title', 'company', 'location', 'site', 'provider', 'source', 'searchTerm', 'description',
  'datePosted', 'firstSeen', 'lastSeen', 'closedAt', 'absentSince', 'createdAt', 'updatedAt', 'applyDeadline', 'expiresAt',
  'isRemote', 'isClosed', 'isAbsent', 'isNew', 'manualEntry', 'offList', 'keptByUser', 'status', 'notFoundThisRun', 'ownerWork',
  'matchScore', 'matchLabel', 'priority', 'applyRecommendation', 'dataStatus', 'readStatus', 'blockedBy', 'eligibility', 'workAuthorization',
  'roleClass', 'engineCoverage', 'aiEnrichment', 'salary', 'salaryMonthlyEur', 'employmentType', 'workMode', 'applicationTracking',
]
/** The three values of a legacy tracking object that the counts read (`countTracking`, `isFollowUpDue`); nothing else of it is sent. */
export const EXTRA_TRACKING_FIELDS = ['applied', 'interviewStage', 'followUpDate']
/** What a row the server already holds may bring: the owner's state on it, never an ad field. */
const OWNER_STATE_FIELDS = ['status', 'keptByUser', 'ownerWork', 'applicationTracking']

const ALLOWED = new Set(EXTRA_ROW_FIELDS)
const ALLOWED_TRACKING = new Set(EXTRA_TRACKING_FIELDS)
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/

const pickTracking = (tracking) => (tracking && typeof tracking === 'object'
  ? Object.fromEntries(EXTRA_TRACKING_FIELDS.filter((f) => tracking[f] !== undefined).map((f) => [f, tracking[f]]))
  : null)

function pick(job, fields) {
  const out = {}
  for (const field of fields) {
    if (job[field] === undefined) continue
    out[field] = field === 'applicationTracking' ? pickTracking(job[field]) : job[field]
  }
  return out
}

/**
 * The rows of the browser's list to send: a row only this browser has (`offList`, or hand-entered) in full, and a row the server may hold that the owner has
 * worked on here as its owner state only. Every other row is left out: the server has it.
 *
 * Slim on purpose (owner decision 2026-11-24: the request cap stays, and is made hard to reach): the ad's text is 88% of a row's bytes, and only a text search
 * reads it, so `description` is sent only with `withText` (the caller sets it while a search is on). Without it a row is about 1.3 KB (1.8 KB at most, measured
 * on the real scored rows), so a 1 MB request holds roughly 780 rows, not 95; an owner-work flag entry is a few hundred bytes.
 */
export function selectExtraRows(storedJobs, { withText = false } = {}) {
  const rows = []
  for (const job of storedJobs ?? []) {
    if (!job || typeof job.jobId !== 'string') continue
    const worked = hasUserData(job)
    if (job.offList === true || job.manualEntry === true) {
      rows.push({ ...pick(job, EXTRA_ROW_FIELDS.filter((f) => f !== 'ownerWork' && (withText || f !== 'description'))), ...(worked ? { ownerWork: true } : {}) })
    } else if (worked) {
      rows.push({ jobId: job.jobId, ...pick(job, OWNER_STATE_FIELDS.filter((f) => f !== 'ownerWork')), ownerWork: true })
    }
  }
  return rows
}

export class ExtraRowsError extends Error {}

/** Refuses a request's `extraRows` that carries a field outside the allowlist, a bad id, or a duplicate. Never quotes a value. Returns the rows as they are. */
export function checkExtraRows(rows) {
  if (rows === undefined || rows === null) return []
  if (!Array.isArray(rows)) throw new ExtraRowsError('extraRows must be a list')
  const seen = new Set()
  rows.forEach((row, i) => {
    if (!row || typeof row !== 'object' || Array.isArray(row)) throw new ExtraRowsError(`extraRows[${i}] must be an object`)
    for (const field of Object.keys(row)) {
      if (!ALLOWED.has(field)) throw new ExtraRowsError(`extraRows[${i}] has a field that is not allowed: ${JSON.stringify(field).slice(0, 40)}`)
    }
    if (typeof row.jobId !== 'string' || !JOB_ID.test(row.jobId)) throw new ExtraRowsError(`extraRows[${i}] has no valid jobId`)
    if (seen.has(row.jobId)) throw new ExtraRowsError(`extraRows[${i}] repeats a jobId`)
    seen.add(row.jobId)
    if (row.ownerWork !== undefined && row.ownerWork !== true) throw new ExtraRowsError(`extraRows[${i}].ownerWork must be true or absent`)
    if (row.applicationTracking !== undefined && row.applicationTracking !== null) {
      const tracking = row.applicationTracking
      if (typeof tracking !== 'object' || Array.isArray(tracking)) throw new ExtraRowsError(`extraRows[${i}].applicationTracking must be an object`)
      for (const field of Object.keys(tracking)) {
        if (!ALLOWED_TRACKING.has(field)) throw new ExtraRowsError(`extraRows[${i}].applicationTracking has a field that is not allowed: ${JSON.stringify(field).slice(0, 40)}`)
      }
    }
  })
  return rows
}

/**
 * The server's stored rows with the browser's rows put in, for one request (nothing is kept). A row the server holds (same `jobId`, or the same address)
 * keeps its ad fields and takes only the owner's state; a row it does not hold is added as it was sent. As on an import (`importJobsFromFile`), a server
 * row with the address of a hand-entered job under another id is that job, and is dropped. Does not change its inputs.
 */
export function applyExtraRows(stored, extraRows) {
  if (!extraRows?.length) return stored
  const byId = new Map(stored.map((row, i) => [row.jobId, i]))
  const byKey = new Map(stored.map((row, i) => [jobMatchKey(row), i]))
  const out = [...stored]
  const added = []
  const manualUrls = new Map()
  for (const extra of extraRows) {
    // The same id is the same row. The same address under another id is the same ad, unless the browser's row is a hand-entered job: that one wins, as on an import.
    const index = byId.get(extra.jobId) ?? (extra.manualEntry !== true && (extra.jobUrl || extra.title) ? byKey.get(jobMatchKey(extra)) : undefined)
    if (index !== undefined) {
      out[index] = { ...out[index], ...pick(extra, OWNER_STATE_FIELDS) }
      continue
    }
    added.push({ ...extra })
    if (extra.manualEntry === true) {
      const url = identityJobUrl(extra.jobUrl)
      if (url) manualUrls.set(url, extra.jobId)
    }
  }
  const kept = out.filter((row) => !(manualUrls.size && manualUrls.get(identityJobUrl(row.jobUrl)) && manualUrls.get(identityJobUrl(row.jobUrl)) !== row.jobId))
  return [...kept, ...added]
}

/** True for a row the browser alone can show in full: the server was sent its filter fields, never its notes or links. */
export const isBrowserOnly = (job) => job?.offList === true || job?.manualEntry === true
