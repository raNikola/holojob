/**
 * The application store (docs/redesign/TRACKER_PLAN.md, Phase 3 A2).
 *
 * data/applications/applications.json is the master; the browser keeps a read
 * cache only. Applications are created once and then only grow by appending
 * events: there is no update or delete path, and every write goes through
 * assertAppendOnly. Frozen copies of what was sent live in
 * data/applications/files/<appId>/. This is the only module that writes there.
 *
 * The tracker settings (stage registry and switches, TRACKER_PLAN 1.6, 1.7) are a second file
 * next to the store. One lock covers both, so a stage change, a retire and a move exclude
 * each other.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import {
  CHANNELS,
  CV_KINDS,
  DISTINCT_REASONS,
  EVENT_TYPES,
  MESSAGE_VIA,
  NUDGE_RULES,
  CLOSED_COLUMNS,
  OUTCOMES,
} from '../src/modules/applications/applicationEnums.js'
import { foldApplication, isActive } from '../src/modules/applications/foldApplication.js'
import {
  RegistryError,
  applyStageOperation,
  boardColumn,
  defaultSettings,
  mergeBackupSettings,
  moveTargets,
  selectableStageKeys,
  settingsProblem,
  withChange,
} from '../src/modules/applications/stageRegistry.js'
import { maskErrorField } from './secret-mask.js'
import {
  LEGACY_CLOSED_STAGES,
  legacyChanges,
  legacyDay,
  legacyKind,
  legacyProblem,
  legacyStageEvent,
  legacyTrackingOf,
  unmappedLegacyKeys,
} from '../src/modules/applications/legacyTracking.js'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, copyToNewFile, replaceFileAtomic } from './atomic-file.js'
import { isCvId } from './cv-store.js'

const STORE_REL = 'data/applications'
const BACKUP_ENTRY_PREFIX = `${STORE_REL}/`
const STORE_VERSION = 1
const MAX_REQUESTS = 200
const SOFT_DUPLICATE_DAYS = 30
const TIME_ZONE = 'Europe/Belgrade'

const APP_ID = /^(app|mig|csv)-[0-9a-f]{16}$/
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/
const REQUEST_ID = /^[A-Za-z0-9-]{8,100}$/
const DATE = /^\d{4}-\d{2}-\d{2}$/

export class StoreError extends Error {
  constructor(status, message, extra = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

// --- paths -----------------------------------------------------------------------------------

export function storePaths(root) {
  const dir = path.join(root, STORE_REL)
  return {
    dir,
    store: path.join(dir, 'applications.json'),
    settings: path.join(dir, 'settings.json'),
    files: path.join(dir, 'files'),
    backups: path.join(root, 'data/backups'),
    cvs: path.join(root, 'data/profile/cvs'),
    resumes: path.join(root, 'data/resumes'),
    scored: path.join(root, 'data/jobs/scored_jobs.json'),
    ledger: path.join(root, 'data/jobs/job_history.json'),
  }
}

export function isAppId(id) {
  return typeof id === 'string' && APP_ID.test(id)
}

function appFilesDir(root, appId) {
  if (!isAppId(appId)) throw new StoreError(400, 'Invalid application id')
  return path.join(storePaths(root).files, appId)
}

// --- helpers ---------------------------------------------------------------------------------

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex')
}

function sameJson(a, b) {
  return canonicalJson(a) === canonicalJson(b)
}

export function snapshotSha(posting) {
  const fields = { ...posting }
  delete fields.snapshotSha256
  return sha256(canonicalJson(fields))
}

/** YYYY-MM-DD in the server's zone, the day nudges and event dates are counted in. */
export function localDay(date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(date)
}

function isValidDate(value) {
  if (typeof value !== 'string' || !DATE.test(value)) return false
  const d = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value
}

function str(value) {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return ''
}

const SERBIAN_LATIN = { č: 'c', ć: 'c', š: 's', ž: 'z', đ: 'dj' }
const LEGAL_SUFFIX = /(^|\s)(d\.o\.o\.|doo|ltd|gmbh|inc|llc|ag)\.?(?=\s|$)/g

/** Key normalization (TRACKER_PLAN section 4). */
export function norm(value) {
  return str(value)
    .toLowerCase()
    .replace(/[čćšžđ]/g, (c) => SERBIAN_LATIN[c])
    .replace(/\s+/g, ' ')
    .replace(LEGAL_SUFFIX, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export function normalizeUrl(value) {
  const raw = str(value).trim()
  if (!raw) return ''
  try {
    const url = new URL(raw)
    url.hash = ''
    for (const key of [...url.searchParams.keys()]) {
      if (key.toLowerCase().startsWith('utm_')) url.searchParams.delete(key)
    }
    return `${url.protocol}//${url.host.toLowerCase()}${url.pathname.replace(/\/+$/, '')}${url.search}`
  } catch {
    return raw.toLowerCase().replace(/\/+$/, '')
  }
}

/** The link used by duplicate checks (6c). Never the identity of an application. */
export function postingKeyFor(posting) {
  if (posting.jobId) return `job:${posting.jobId}`
  const url = normalizeUrl(posting.url)
  if (url) return `url:${url}`
  return `tcl:${norm(posting.company)}|${norm(posting.title)}|${norm(posting.location)}`
}

function safeFileName(name, fallback) {
  const clean = str(name).replace(/[^\w .()[\]-]/g, '_').replace(/^[ .]+/, '').slice(0, 120)
  return clean || fallback
}

// --- load, atomic save, lock -----------------------------------------------------------------

export function emptyStore() {
  return { version: STORE_VERSION, updatedAt: null, requests: {}, applications: {} }
}

/** A missing store is empty. An unreadable one throws, so nothing is ever written over it. */
export function loadStore(root) {
  const file = storePaths(root).store
  if (!fs.existsSync(file)) return emptyStore()
  let store
  try {
    store = JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch (e) {
    throw new StoreError(500, `applications.json is unreadable, refusing to touch it: ${e.message}`)
  }
  if (store?.version !== STORE_VERSION || typeof store.applications !== 'object') {
    throw new StoreError(500, 'applications.json has an unknown shape, refusing to touch it')
  }
  store.requests ??= {}
  return store
}

/** Replace a file whole (atomic-file.js). A failure leaves the target as it was. New files and folders are private. */
export function writeFileAtomic(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: PRIVATE_DIR_MODE })
  replaceFileAtomic(file, data, { mode: PRIVATE_FILE_MODE })
}

function saveStore(root, prev, next) {
  assertStoreAppendOnly(prev, next)
  writeFileAtomic(storePaths(root).store, `${JSON.stringify(next, null, 2)}\n`)
}

// --- tracker settings ------------------------------------------------------------------------

/**
 * The tracker settings. A missing file is the defaults (nothing is written until the first change).
 * An unreadable or malformed one throws, so nothing is ever written over it and no stage is
 * guessed from defaults.
 */
export function loadSettings(root) {
  const file = storePaths(root).settings
  if (!fs.existsSync(file)) return defaultSettings()
  let settings
  try {
    settings = JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch (e) {
    throw new StoreError(500, `settings.json is unreadable, refusing to touch it: ${e.message}`)
  }
  const problem = settingsProblem(settings)
  if (problem) throw new StoreError(500, `settings.json is invalid (${problem}), refusing to touch it`)
  settings.changes ??= []
  return settings
}

function saveSettings(root, settings) {
  const problem = settingsProblem(settings)
  if (problem) throw new StoreError(500, `refusing to write invalid settings (${problem})`)
  writeFileAtomic(storePaths(root).settings, `${JSON.stringify(settings, null, 2)}\n`)
}

/** The settings for a write that creates or appends: refused while tracking is off. */
function settingsForWrite(root) {
  const settings = loadSettings(root)
  if (!settings.trackingEnabled) {
    throw new StoreError(409, 'Application tracking is off', { code: 'tracking_disabled' })
  }
  return settings
}

const locks = new Map()

/** Serialize every read-check-write on the store and its settings, so parallel requests lose nothing. */
function withLock(root, fn) {
  const key = storePaths(root).dir
  const run = (locks.get(key) ?? Promise.resolve()).then(fn)
  locks.set(key, run.catch(() => {}))
  return run
}

// --- the append-only guard -------------------------------------------------------------------

function fail(message) {
  throw new StoreError(500, `append-only violation: ${message}`)
}

/** Throws unless `next` is `prev` with zero or more events added at the end. */
export function assertAppendOnly(prev, next) {
  if (!next) fail(`application ${prev.id} removed`)
  for (const field of ['id', 'createdAt', 'origin', 'posting', 'attempt', 'legacy']) {
    if (!sameJson(prev[field] ?? null, next[field] ?? null)) fail(`${prev.id}: ${field} changed`)
  }
  const before = prev.events ?? []
  const after = next.events ?? []
  if (after.length < before.length) fail(`${prev.id}: events removed`)
  before.forEach((event, i) => {
    if (!sameJson(event, after[i])) fail(`${prev.id}: event ${i + 1} rewritten`)
  })
  assertEventLog(next)
}

/** seq runs 1..n with no gap, and every id is <appId>:<seq>. */
function assertEventLog(app) {
  ;(app.events ?? []).forEach((event, i) => {
    if (event.seq !== i + 1 || event.id !== `${app.id}:${i + 1}`) fail(`${app.id}: event ${i + 1} out of sequence`)
  })
  if (app.events?.[0]?.type !== 'applied') fail(`${app.id}: first event is not applied`)
}

export function assertStoreAppendOnly(prev, next) {
  for (const [id, app] of Object.entries(prev.applications)) {
    assertAppendOnly(app, next.applications[id])
  }
}

// --- snapshot --------------------------------------------------------------------------------

function readJson(file) {
  try {
    return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf-8')) : null
  } catch {
    return null
  }
}

/** The posting as discovery or the browser saw it, from the first source that has it (2.2 order). */
function findPostingSource(root, jobId, browserPosting) {
  const paths = storePaths(root)
  const scored = readJson(paths.scored)
  const fromScored = Array.isArray(scored?.jobs) ? scored.jobs.find((j) => j?.jobId === jobId) : null
  if (fromScored) return { job: fromScored, capturedFrom: 'scored_jobs' }
  const fromLedger = readJson(paths.ledger)?.jobs?.[jobId]?.job
  if (fromLedger) return { job: fromLedger, capturedFrom: 'job_history' }
  if (browserPosting && typeof browserPosting === 'object') return { job: browserPosting, capturedFrom: 'browser' }
  return null
}

function buildPosting(root, body, capturedAt) {
  let source
  let jobId = null
  if (body.jobId !== undefined && body.jobId !== null) {
    if (typeof body.jobId !== 'string' || !JOB_ID.test(body.jobId)) throw new StoreError(400, 'Invalid jobId')
    jobId = body.jobId
    source = findPostingSource(root, jobId, body.posting)
    if (!source) throw new StoreError(400, `Job ${jobId} not found and no posting sent`)
  } else {
    if (!body.posting || typeof body.posting !== 'object') throw new StoreError(400, 'A jobId or a posting is required')
    source = { job: body.posting, capturedFrom: 'manual' }
  }
  return postingFromJob(source.job, jobId, source.capturedFrom, capturedAt, false)
}

/** The frozen posting record of a job record; throws when it has no title or company. */
function postingFromJob(job, jobId, capturedFrom, capturedAt, capturedAfterApply) {
  const description = str(job.description)
  const posting = {
    jobId,
    postingKey: '',
    title: str(job.title).trim(),
    company: str(job.company).trim(),
    location: str(job.location),
    url: str(job.jobUrl || job.url),
    source: str(job.source),
    provider: str(job.provider),
    datePosted: str(job.datePosted),
    salary: str(job.salary),
    employmentType: str(job.employmentType),
    workMode: str(job.workMode || job.llmFacts?.workMode),
    isRemote: typeof job.isRemote === 'boolean' ? job.isRemote : null,
    description,
    descriptionMissing: !description.trim(),
    capturedFrom,
    capturedAt,
    capturedAfterApply,
  }
  if (!posting.title || !posting.company) throw new StoreError(400, 'The posting needs a title and a company')
  posting.postingKey = postingKeyFor(posting)
  posting.snapshotSha256 = snapshotSha(posting)
  return posting
}

// --- frozen files ----------------------------------------------------------------------------

/** Where the sent CV comes from. External and unknown CVs have no file on the server yet. */
function cvSource(root, cv, jobId) {
  const paths = storePaths(root)
  if (cv.kind === 'library') {
    if (!isCvId(cv.cvLibraryId)) throw new StoreError(400, 'Invalid cvLibraryId')
    const file = path.join(paths.cvs, `${cv.cvLibraryId}.pdf`)
    if (!fs.existsSync(file)) throw new StoreError(400, 'The library CV file does not exist')
    return { file, fileName: safeFileName(cv.fileName, `cv-${cv.cvLibraryId}.pdf`) }
  }
  if (cv.kind === 'tailored') return tailoredSource(paths, jobId, cv.fileName, 'tailored CV')
  return null
}

function tailoredSource(paths, jobId, fileName, what) {
  if (!jobId) throw new StoreError(400, `A ${what} needs a jobId`)
  const name = path.basename(str(fileName))
  if (!name || name !== fileName) throw new StoreError(400, `Invalid ${what} file name`)
  const file = path.join(paths.resumes, jobId, name)
  if (!fs.existsSync(file)) throw new StoreError(400, `The ${what} file does not exist`)
  return { file, fileName: name }
}

/** Copy (never link) a file into the application's folder; returns its sha256. */
function freezeFile(dir, src) {
  fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
  const dest = path.join(dir, src.fileName)
  copyToNewFile(src.file, dest, PRIVATE_FILE_MODE)
  return sha256(fs.readFileSync(dest))
}

// --- duplicate rules (6c) --------------------------------------------------------------------

function latest(apps) {
  return [...apps].sort((a, b) => (a.createdAt === b.createdAt ? (a.id < b.id ? -1 : 1) : a.createdAt < b.createdAt ? -1 : 1)).at(-1)
}

/**
 * Create rule (6c): checks a new attempt against the active applications with the same posting
 * key. Returns the conflicting application, if any. Restore and reopen use `findCompetitor`.
 */
function findConflict(store, { postingKey, channel, cvSha, reason }) {
  const open = Object.values(store.applications)
    .filter((app) => app.posting.postingKey === postingKey && isActive(app))
    .filter((app) => !foldApplication(app).outcome)
  let blocking = open
  if (reason === 'different_channel') {
    blocking = open.filter((app) => app.attempt.channel === channel)
  } else if (reason === 'resubmitted_new_cv') {
    blocking = open.filter((app) => app.attempt.channel === channel && (!cvSha || app.attempt.cv.sha256 === cvSha))
  }
  return blocking.length ? latest(blocking) : null
}

/**
 * Two applications compete (1.9) when both are open and not voided, name the same posting key
 * and the same channel, unless their CVs are both known and different and one of them claimed
 * `resubmitted_new_cv`.
 */
function competes(a, b) {
  if (a.id === b.id || a.posting.postingKey !== b.posting.postingKey) return false
  if (a.attempt.channel !== b.attempt.channel) return false
  const shaA = foldApplication(a).cv?.sha256 ?? null
  const shaB = foldApplication(b).cv?.sha256 ?? null
  const verifiedNewCv = shaA && shaB && shaA !== shaB
    && (a.attempt.distinctReason === 'resubmitted_new_cv' || b.attempt.distinctReason === 'resubmitted_new_cv')
  return !verifiedNewCv
}

/** The latest open application that `app` would compete with once it is open itself, if any. */
function findCompetitor(store, app) {
  const rivals = Object.values(store.applications)
    .filter((other) => isActive(other) && !foldApplication(other).outcome && competes(app, other))
  return rivals.length ? latest(rivals) : null
}

function refuseCompetitor(store, app, message) {
  const rival = findCompetitor(store, app)
  if (rival) throw new StoreError(409, message, { conflictingId: rival.id })
}

function softDuplicates(store, posting, now) {
  const since = now.getTime() - SOFT_DUPLICATE_DAYS * 86400000
  return Object.values(store.applications).filter((app) => app.posting.postingKey !== posting.postingKey
    && norm(app.posting.company) === norm(posting.company)
    && norm(app.posting.title) === norm(posting.title)
    && Date.parse(app.createdAt) >= since
    && isActive(app) && !foldApplication(app).outcome)
}

// --- create ----------------------------------------------------------------------------------

function validateAttempt(attempt, today) {
  if (!attempt || typeof attempt !== 'object') throw new StoreError(400, 'attempt is required')
  if (!CHANNELS.includes(attempt.channel)) throw new StoreError(400, 'Invalid channel')
  if (!isValidDate(attempt.appliedDate)) throw new StoreError(400, 'appliedDate must be YYYY-MM-DD')
  if (attempt.appliedDate > today) throw new StoreError(400, 'appliedDate is in the future')
  const cv = attempt.cv
  if (!cv || !CV_KINDS.includes(cv.kind)) throw new StoreError(400, 'Invalid cv.kind')
}

/**
 * Create one application. Returns { status, application, warnings }; status is 201 for a new
 * record and 200 when `requestId` was seen before (the first result, nothing written).
 */
export function createApplication(root, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    settingsForWrite(root)
    if (!body || typeof body !== 'object') throw new StoreError(400, 'Body must be an object')
    const { requestId } = body
    if (typeof requestId !== 'string' || !REQUEST_ID.test(requestId) || /^\d+$/.test(requestId)) {
      throw new StoreError(400, 'A requestId (UUID) is required')
    }
    const store = loadStore(root)
    const known = store.requests[requestId]
    if (known && store.applications[known]) {
      return { status: 200, application: store.applications[known], warnings: [], replayed: true }
    }

    const at = now()
    const createdAt = at.toISOString()
    const attempt = body.attempt
    validateAttempt(attempt, localDay(at))
    const claimed = body.newAttempt?.distinctReason ?? null
    if (claimed !== null && !DISTINCT_REASONS.includes(claimed)) throw new StoreError(400, 'Invalid distinctReason')

    const posting = buildPosting(root, body, createdAt)
    const cvSrc = cvSource(root, attempt.cv, posting.jobId)
    const letterSrc = attempt.coverLetter?.fileName
      ? tailoredSource(storePaths(root), posting.jobId, attempt.coverLetter.fileName, 'cover letter')
      : null
    if (cvSrc && letterSrc && cvSrc.fileName === letterSrc.fileName) {
      throw new StoreError(400, 'The CV and the cover letter have the same file name')
    }

    let appId
    do appId = `app-${crypto.randomBytes(8).toString('hex')}`
    while (store.applications[appId] || fs.existsSync(appFilesDir(root, appId)))

    const dir = appFilesDir(root, appId)
    try {
      const cvSha = cvSrc ? freezeFile(dir, cvSrc) : null
      const letterSha = letterSrc ? freezeFile(dir, letterSrc) : null

      const conflict = findConflict(store, {
        postingKey: posting.postingKey, channel: attempt.channel, cvSha, reason: claimed,
      })
      if (conflict) {
        throw new StoreError(409, 'An open application for this posting already exists', { conflictingId: conflict.id })
      }
      const earlier = Object.values(store.applications)
        .filter((app) => app.posting.postingKey === posting.postingKey && isActive(app))
      const anyOpen = earlier.some((app) => !foldApplication(app).outcome)

      const application = {
        id: appId,
        createdAt,
        origin: 'manual',
        posting,
        attempt: {
          channel: attempt.channel,
          channelDetail: str(attempt.channelDetail),
          applicationUrl: str(attempt.applicationUrl),
          appliedDate: attempt.appliedDate,
          cv: {
            kind: attempt.cv.kind,
            cvLibraryId: attempt.cv.kind === 'library' ? attempt.cv.cvLibraryId : null,
            label: str(attempt.cv.label),
            fileName: cvSrc?.fileName ?? null,
            sha256: cvSha,
          },
          coverLetter: { fileName: letterSrc?.fileName ?? null, sha256: letterSha },
          previousApplicationId: earlier.length ? latest(earlier).id : null,
          distinctReason: !earlier.length ? null : anyOpen ? claimed : 'reapply_after_outcome',
        },
        legacy: null,
        events: [{
          id: `${appId}:1`, seq: 1, type: 'applied', at: createdAt,
          date: attempt.appliedDate, source: 'user', data: {},
        }],
      }

      // The 6c rules above are the stricter ones; this is the invariant itself (1.9), which also
      // counts a CV that is unknown, or that a later correction made equal, as not verified.
      refuseCompetitor(store, application, 'An open application for this posting already exists')
      const next = {
        ...store,
        updatedAt: createdAt,
        requests: { ...store.requests, [requestId]: appId },
        applications: { ...store.applications, [appId]: application },
      }
      const ids = Object.keys(next.requests)
      for (const old of ids.slice(0, Math.max(0, ids.length - MAX_REQUESTS))) delete next.requests[old]
      const warnings = softDuplicates(store, posting, at).length ? ['possible_duplicate'] : []
      saveStore(root, store, next)
      return { status: 201, application, warnings }
    } catch (e) {
      fs.rmSync(dir, { recursive: true, force: true })
      throw e
    }
  })
}

// --- events ----------------------------------------------------------------------------------

const USER_EVENT_DATA = {
  stage_changed: { required: ['stage'], optional: [] },
  outcome_set: { required: ['outcome'], optional: [] },
  outcome_cleared: { required: ['reason'], optional: [] },
  note_added: { required: ['text'], optional: [] },
  contact_added: { required: [], optional: ['role', 'name', 'email', 'linkedin'] },
  contact_updated: { required: ['contactId'], optional: ['role', 'name', 'email', 'linkedin'] },
  message_sent: { required: ['via'], optional: ['contactId', 'summary'] },
  reply_received: { required: ['via'], optional: ['contactId', 'summary'] },
  follow_up_set: { required: ['dueDate'], optional: [] },
  follow_up_done: { required: [], optional: ['how'] },
  nudge_snoozed: { required: ['rule', 'until'], optional: [] },
  assignment_due: { required: ['dueDate'], optional: [] },
  offer_deadline: { required: ['dueDate'], optional: [] },
  event_voided: { required: ['eventId', 'reason'], optional: [] },
  application_voided: { required: ['reason'], optional: [] },
  application_restored: { required: ['reason'], optional: [] },
  applied_date_corrected: { required: ['appliedDate'], optional: [] },
  cv_recorded: { required: ['kind'], optional: ['cvLibraryId', 'label', 'fileName', 'reason'] },
}

const ENUM_FIELDS = { outcome: OUTCOMES, via: MESSAGE_VIA, rule: NUDGE_RULES, kind: CV_KINDS }
const DATE_FIELDS = ['dueDate', 'until', 'appliedDate']
const CONTACT_FIELDS = ['role', 'name', 'email', 'linkedin']
// event_voided may not target these: a void is undone only by a restore, and the
// first event is undone only by voiding the application.
const NOT_VOIDABLE = ['applied', 'event_voided', 'application_voided', 'application_restored']
const MOVED_ON_BOARD = 'moved on the board'

function validateEventData(app, type, data, settings, today) {
  const spec = USER_EVENT_DATA[type]
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new StoreError(400, 'data must be an object')
  for (const key of Object.keys(data)) {
    if (!spec.required.includes(key) && !spec.optional.includes(key)) {
      throw new StoreError(400, `${type} does not take data.${key}`)
    }
  }
  for (const key of spec.required) {
    if (data[key] === undefined || data[key] === null || data[key] === '') {
      throw new StoreError(400, `${type} needs data.${key}`)
    }
  }
  for (const [key, value] of Object.entries(data)) {
    if (ENUM_FIELDS[key] && !ENUM_FIELDS[key].includes(value)) throw new StoreError(400, `Invalid data.${key}`)
    else if (DATE_FIELDS.includes(key) && !isValidDate(value)) throw new StoreError(400, `data.${key} must be YYYY-MM-DD`)
    else if (typeof value !== 'string') throw new StoreError(400, `data.${key} must be a string`)
  }

  const folded = foldApplication(app)
  const contactIds = new Set(folded.contacts.map((c) => c.contactId))
  if (data.contactId !== undefined && type !== 'contact_added' && !contactIds.has(data.contactId)) {
    throw new StoreError(400, `Unknown contact ${data.contactId}`)
  }
  if (type === 'contact_added' && !['name', 'email', 'linkedin'].some((k) => str(data[k]).trim())) {
    throw new StoreError(400, 'A contact needs a name, an e-mail or a LinkedIn link')
  }
  if (type === 'contact_updated' && !CONTACT_FIELDS.some((k) => data[k] !== undefined)) {
    throw new StoreError(400, 'contact_updated needs at least one changed field')
  }
  if (type === 'event_voided') {
    const target = app.events.find((e) => e.id === data.eventId)
    if (!target) throw new StoreError(400, `Unknown event ${data.eventId}`)
    if (NOT_VOIDABLE.includes(target.type)) throw new StoreError(400, `A ${target.type} event cannot be voided`)
    if (app.events.some((e) => e.type === 'event_voided' && e.data.eventId === data.eventId)) {
      throw new StoreError(400, `Event ${data.eventId} is already voided`)
    }
  }
  if (type === 'stage_changed') {
    if (!selectableStageKeys(settings).includes(data.stage)) {
      throw new StoreError(400, `${JSON.stringify(data.stage)} is not an active stage`)
    }
    if (folded.outcome) throw new StoreError(400, 'A closed application cannot change stage; reopen it first')
  }
  if (type === 'outcome_set' && folded.outcome) {
    throw new StoreError(400, `The application already has the outcome ${folded.outcome}; clear it first`)
  }
  if (type === 'outcome_cleared' && !folded.outcome) throw new StoreError(400, 'The application has no outcome to clear')
  if (type === 'applied_date_corrected' && data.appliedDate > today) {
    throw new StoreError(400, 'appliedDate is in the future')
  }
  if (type === 'cv_recorded') {
    if (data.kind === 'unknown') throw new StoreError(400, 'A recorded CV cannot be unknown')
    if (folded.cv?.kind !== 'unknown' && !str(data.reason).trim()) {
      throw new StoreError(400, 'Correcting a recorded CV needs a reason')
    }
  }
  if (type === 'application_voided' && folded.voided) throw new StoreError(400, 'The application is already voided')
  if (type === 'application_restored' && !folded.voided) throw new StoreError(400, 'The application is not voided')
  if (folded.voided && type !== 'application_restored') {
    throw new StoreError(400, 'A voided application is read-only; restore it first')
  }
}

function makeEvent(appId, seq, type, at, date, data) {
  return { id: `${appId}:${seq}`, seq, type, at, date, source: 'user', data }
}

function eventDay(body, today) {
  const date = body.date ?? today
  if (!isValidDate(date)) throw new StoreError(400, 'date must be YYYY-MM-DD')
  if (date > today) throw new StoreError(400, 'date cannot be later than today; use a *_due or follow_up_set event')
  return date
}

/** Copy a file into the application's folder under a name nobody has used, never over one. */
function freezeUnique(dir, src) {
  fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
  const ext = path.extname(src.fileName)
  const stem = src.fileName.slice(0, src.fileName.length - ext.length)
  for (let n = 1; ; n += 1) {
    const fileName = n === 1 ? src.fileName : `${stem}-${n}${ext}`
    const dest = path.join(dir, fileName)
    try {
      copyToNewFile(src.file, dest, PRIVATE_FILE_MODE)
    } catch (e) {
      if (e.code === 'EEXIST') continue
      throw e
    }
    return { fileName, dest, sha256: sha256(fs.readFileSync(dest)) }
  }
}

/** The data a `cv_recorded` event stores: the server decides fileName and sha256. */
function recordCv(root, app, data) {
  const cv = { kind: data.kind, cvLibraryId: data.cvLibraryId, label: data.label, fileName: data.fileName }
  const src = cvSource(root, cv, app.posting.jobId)
  const frozen = src ? freezeUnique(appFilesDir(root, app.id), src) : null
  const stored = {
    kind: data.kind,
    cvLibraryId: data.kind === 'library' ? data.cvLibraryId : null,
    label: str(data.label),
    fileName: frozen?.fileName ?? null,
    sha256: frozen?.sha256 ?? null,
  }
  if (str(data.reason).trim()) stored.reason = data.reason
  return { stored, copied: frozen?.dest ?? null }
}

/** Write the events in one save, checked by assertAppendOnly. Returns the saved application. */
function saveEvents(root, store, app, events, at) {
  const nextApp = { ...app, events: [...app.events, ...events] }
  saveStore(root, store, {
    ...store,
    updatedAt: at,
    applications: { ...store.applications, [app.id]: nextApp },
  })
  return nextApp
}

/**
 * Append ONE event. The server assigns id, seq, at and source; the body holds
 * { type, date, data } and nothing else. Returns { status: 201, application, event }.
 */
export function appendEvent(root, appId, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const settings = settingsForWrite(root)
    if (!isAppId(appId)) throw new StoreError(400, 'Invalid application id')
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new StoreError(400, 'Body must be one event')
    for (const key of Object.keys(body)) {
      if (!['type', 'date', 'data'].includes(key)) throw new StoreError(400, `An event body cannot carry "${key}"`)
    }
    const store = loadStore(root)
    const app = store.applications[appId]
    if (!app) throw new StoreError(404, 'Application not found')
    const { type } = body
    if (!USER_EVENT_DATA[type]) {
      throw new StoreError(400, EVENT_TYPES.includes(type) ? `${type} cannot be appended` : 'Unknown event type')
    }
    const at = now()
    const today = localDay(at)
    const date = eventDay(body, today)
    let data = { ...(body.data ?? {}) }
    validateEventData(app, type, data, settings, today)

    // Whatever brings an application back to open must not leave two that compete (1.9).
    if (type === 'application_restored' && !foldApplication(app).outcome) {
      refuseCompetitor(store, app, 'Restoring would duplicate an open application')
    }
    if (type === 'outcome_cleared') {
      refuseCompetitor(store, app, 'Reopening would duplicate an open application')
    }
    if (type === 'contact_added') {
      const added = app.events.filter((e) => e.type === 'contact_added').length
      Object.assign(data, { contactId: `c${added + 1}` })
    }

    let copied = null
    try {
      if (type === 'cv_recorded') {
        ;({ stored: data, copied } = recordCv(root, app, data))
        const folded = foldApplication(app)
        if (!folded.voided && !folded.outcome) {
          const probe = { ...app, events: [...app.events, makeEvent(app.id, app.events.length + 1, type, at.toISOString(), date, data)] }
          refuseCompetitor(store, probe, 'This CV would make the application duplicate an open one')
        }
      }
      const event = makeEvent(appId, app.events.length + 1, type, at.toISOString(), date, data)
      const nextApp = saveEvents(root, store, app, [event], event.at)
      return { status: 201, application: nextApp, event }
    } catch (e) {
      if (copied) fs.rmSync(copied, { force: true })
      throw e
    }
  })
}

// --- move (3.1) ------------------------------------------------------------------------------

/**
 * The board's drag and quick-move and the Job Details stage select. Body { toStage, date? }: the
 * server builds the events (stage_changed, or outcome_set / outcome_cleared) and appends them in
 * ONE save. Moving to the column the application is already in writes nothing.
 * Returns { status: 200, application, events, changed }.
 */
export function moveApplication(root, appId, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const settings = settingsForWrite(root)
    if (!isAppId(appId)) throw new StoreError(400, 'Invalid application id')
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new StoreError(400, 'Body must be an object')
    for (const key of Object.keys(body)) {
      if (!['toStage', 'date'].includes(key)) throw new StoreError(400, `A move body cannot carry "${key}"`)
    }
    const store = loadStore(root)
    const app = store.applications[appId]
    if (!app) throw new StoreError(404, 'Application not found')
    const folded = foldApplication(app)
    if (folded.voided) throw new StoreError(400, 'A voided application cannot be moved; restore it first')
    const { toStage } = body
    if (!moveTargets(settings).includes(toStage)) {
      throw new StoreError(400, `${JSON.stringify(toStage)} is not an active stage or a closed column`)
    }
    const at = now()
    const date = eventDay(body, localDay(at))

    const plan = []
    if (CLOSED_COLUMNS.includes(toStage)) {
      if (folded.outcome !== toStage) {
        if (folded.outcome) plan.push(['outcome_cleared', { reason: MOVED_ON_BOARD }])
        plan.push(['outcome_set', { outcome: toStage }])
      }
    } else if (folded.outcome) {
      plan.push(['outcome_cleared', { reason: MOVED_ON_BOARD }])
      if (folded.stage !== toStage) plan.push(['stage_changed', { stage: toStage }])
      refuseCompetitor(store, app, 'Reopening would duplicate an open application')
    } else if (folded.stage !== toStage) {
      plan.push(['stage_changed', { stage: toStage }])
    }
    if (!plan.length) return { status: 200, application: app, events: [], changed: false }

    const stamp = at.toISOString()
    const events = plan.map(([type, data], i) => makeEvent(appId, app.events.length + 1 + i, type, stamp, date, data))
    return { status: 200, application: saveEvents(root, store, app, events, stamp), events, changed: true }
  })
}

// --- settings and the stage registry (1.6, 1.7) ----------------------------------------------

/** Non-voided applications per board column (closed ones count under their outcome), for Settings. */
export function stageCounts(store, settings) {
  const counts = Object.fromEntries([...selectableStageKeys(settings), ...CLOSED_COLUMNS, 'closed', 'unfiled'].map((k) => [k, 0]))
  for (const app of Object.values(store.applications)) {
    const column = boardColumn(foldApplication(app), settings)
    if (column) counts[column] += 1
  }
  return counts
}

function openCountIn(store, key) {
  return Object.values(store.applications).filter((app) => {
    const folded = foldApplication(app)
    return !folded.voided && !folded.outcome && folded.stage === key
  }).length
}

/** Settings and the per-column counts. Needs a readable store as well as readable settings. */
export function readSettings(root) {
  const settings = loadSettings(root)
  return { settings, counts: stageCounts(loadStore(root), settings) }
}

/** The two switches. Stays open while tracking is off, or tracking could never be switched back on. */
export function changeSettings(root, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new StoreError(400, 'Body must be an object')
    const switches = ['trackingEnabled', 'followUpReminders']
    for (const key of Object.keys(body)) {
      if (!switches.includes(key)) throw new StoreError(400, `Settings do not take "${key}"`)
      if (typeof body[key] !== 'boolean') throw new StoreError(400, `${key} must be true or false`)
    }
    if (!Object.keys(body).length) throw new StoreError(400, 'Nothing to change')
    let settings = loadSettings(root)
    const stamp = now().toISOString()
    let changed = false
    for (const key of switches.filter((k) => body[k] !== undefined && body[k] !== settings[k])) {
      settings = withChange({ ...settings, [key]: body[key] }, { action: 'switch', key, old: settings[key], new: body[key] }, stamp)
      changed = true
    }
    // the counts are read before the write, so a failure here leaves the settings as they were
    const counts = stageCounts(loadStore(root), settings)
    if (changed) saveSettings(root, settings)
    return { status: 200, settings, counts }
  })
}

/** One registry operation: add, rename, move, retire or unretire. The retire count runs under the lock. */
export function changeStageRegistry(root, body, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const settings = settingsForWrite(root)
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new StoreError(400, 'Body must be an object')
    for (const key of Object.keys(body)) {
      if (!['op', 'key', 'label', 'dir', 'interview'].includes(key)) throw new StoreError(400, `A stage operation does not take "${key}"`)
    }
    let result
    try {
      result = applyStageOperation(settings, body, (key) => openCountIn(loadStore(root), key))
    } catch (e) {
      if (e instanceof RegistryError) throw new StoreError(e.status, e.message, e.extra)
      throw e
    }
    const next = result.change ? withChange(result.settings, result.change, now().toISOString()) : settings
    const counts = stageCounts(loadStore(root), next)
    if (result.change) saveSettings(root, next)
    return { status: 200, changed: Boolean(result.change), settings: next, counts }
  })
}

// --- frozen file read ------------------------------------------------------------------------

/** Every frozen file an application names: the attempt's CV and cover letter, and each cv_recorded copy. */
function recordedFiles(app) {
  const recorded = [app.attempt.cv, app.attempt.coverLetter]
  for (const event of app.events ?? []) if (event.type === 'cv_recorded') recorded.push(event.data)
  return recorded.filter((f) => f?.fileName)
}

/** Path of a frozen file, only for a name recorded on the application. */
export function applicationFilePath(root, appId, name) {
  if (!isAppId(appId)) throw new StoreError(400, 'Invalid application id')
  const app = loadStore(root).applications[appId]
  if (!app) throw new StoreError(404, 'Application not found')
  if (!recordedFiles(app).some((f) => f.fileName === name)) throw new StoreError(404, 'File not found')
  const file = path.join(appFilesDir(root, appId), name)
  if (!fs.existsSync(file)) throw new StoreError(404, 'File not found')
  return file
}

// --- backup restore merge (3.1) --------------------------------------------------------------

/** True for a backup zip entry that belongs to this store; such entries go to mergeFromBackup. */
export function isStoreBackupEntry(name) {
  return name.startsWith(BACKUP_ENTRY_PREFIX)
}

function backupStamp(date) {
  return date.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15)
}

function uniqueDir(base) {
  let dir = base
  for (let n = 2; fs.existsSync(dir); n += 1) dir = `${base}-${n}`
  return dir
}

function wellFormed(id, app) {
  try {
    if (!isAppId(id) || app?.id !== id || !app.posting || !app.attempt || !Array.isArray(app.events)) return false
    assertEventLog(app)
    return true
  } catch {
    return false
  }
}

/**
 * The settings rule of 3.1 step 5. No current file: the backup's file is written as it is.
 * Both exist: the current switches, labels and order win, and a key found only in the backup is
 * appended as retired with its label. A stage is never dropped. Unreadable settings on either
 * side are reported and left alone.
 */
function mergeSettingsFromBackup(root, entry, report, now) {
  const paths = storePaths(root)
  let backup
  try {
    backup = JSON.parse(Buffer.from(entry.data).toString('utf-8'))
  } catch (e) {
    report.conflicts.push({ appId: null, reason: `backup settings.json unreadable: ${e.message}` })
    return 'kept'
  }
  const problem = settingsProblem(backup)
  if (problem) {
    report.conflicts.push({ appId: null, reason: `backup settings.json invalid (${problem}); current kept` })
    return 'kept'
  }
  if (!fs.existsSync(paths.settings)) {
    writeFileAtomic(paths.settings, entry.data)
    return 'written'
  }
  let current
  try {
    current = loadSettings(root)
  } catch (e) {
    report.conflicts.push({ appId: null, reason: `${e.message}; backup settings not merged` })
    return 'kept'
  }
  const { settings, added } = mergeBackupSettings(current, backup, now().toISOString())
  if (!added.length) return 'unchanged'
  saveSettings(root, { ...settings, updatedAt: now().toISOString() })
  return 'merged'
}

/**
 * Merge the store entries of a backup zip into the current store. It adds applications
 * and events, never removes or rewrites one: an application in both is replaced only by a
 * longer log that has the current one as its prefix. Missing frozen files are added,
 * existing ones never overwritten. The current store and settings are backed up first.
 *
 * `entries` are { name, data } with names as in the zip (data/applications/...).
 */
export function mergeFromBackup(root, entries, { now = () => new Date() } = {}) {
  return withLock(root, () => {
    const paths = storePaths(root)
    const report = {
      added: [], extended: [], unchanged: [], conflicts: [], filesAdded: [], ignored: [], backupPath: null, settings: null,
    }
    const storeEntry = entries.find((e) => e.name === `${STORE_REL}/applications.json`)
    const settingsEntry = entries.find((e) => e.name === `${STORE_REL}/settings.json`)
    const fileEntries = []
    for (const entry of entries) {
      if (entry === storeEntry || entry === settingsEntry) continue
      const m = new RegExp(`^${STORE_REL}/files/([^/]+)/([^/]+)$`).exec(entry.name)
      if (m && isAppId(m[1])) fileEntries.push({ appId: m[1], name: m[2], data: entry.data })
      else report.ignored.push(entry.name)
    }

    const current = loadStore(root)
    const existing = [paths.store, paths.settings].filter((file) => fs.existsSync(file))
    if (existing.length) {
      const dir = uniqueDir(path.join(paths.backups, `applications-${backupStamp(now())}`))
      fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
      for (const file of existing) copyToNewFile(file, path.join(dir, path.basename(file)), PRIVATE_FILE_MODE)
      report.backupPath = path.relative(root, dir)
    }

    let incoming = {}
    if (storeEntry) {
      try {
        const parsed = JSON.parse(Buffer.from(storeEntry.data).toString('utf-8'))
        if (parsed?.version !== STORE_VERSION) throw new Error(`unknown version ${parsed?.version}`)
        incoming = parsed.applications ?? {}
      } catch (e) {
        report.conflicts.push({ appId: null, reason: `backup applications.json unreadable: ${e.message}` })
      }
    }

    const merged = { ...current.applications }
    for (const [id, app] of Object.entries(incoming)) {
      if (!wellFormed(id, app)) {
        report.conflicts.push({ appId: id, reason: 'malformed record in backup' })
        continue
      }
      const mine = merged[id]
      if (!mine) {
        merged[id] = app
        report.added.push(id)
        continue
      }
      const longer = app.events.length > mine.events.length
      try {
        if (longer) assertAppendOnly(mine, app)
        else assertAppendOnly(app, mine)
      } catch {
        report.conflicts.push({ appId: id, reason: 'histories differ; current kept' })
        continue
      }
      if (longer) {
        merged[id] = app
        report.extended.push(id)
      } else {
        report.unchanged.push(id)
      }
    }

    const next = { ...current, applications: merged }
    if (report.added.length || report.extended.length) {
      next.updatedAt = now().toISOString()
      saveStore(root, current, next)
    }

    if (settingsEntry) report.settings = mergeSettingsFromBackup(root, settingsEntry, report, now)

    for (const file of fileEntries) {
      const app = merged[file.appId]
      const recorded = app && recordedFiles(app).find((f) => f.fileName === file.name)
      if (!recorded) {
        report.ignored.push(`${STORE_REL}/files/${file.appId}/${file.name}`)
        continue
      }
      const dest = path.join(appFilesDir(root, file.appId), file.name)
      if (fs.existsSync(dest)) continue
      if (recorded.sha256 && sha256(file.data) !== recorded.sha256) {
        report.conflicts.push({ appId: file.appId, reason: `${file.name} does not match its recorded sha256` })
        continue
      }
      writeFileAtomic(dest, file.data)
      report.filesAdded.push(`${file.appId}/${file.name}`)
    }
    return report
  })
}

// --- migration from applicationTracking (2, 6d) ----------------------------------------------

const MIGRATION_LOG = 'migration.json'
const MAX_MIGRATION_RUNS = 50
const EPOCH = '1970-01-01T00:00:00.000Z'

/** The hash a preview and its apply must agree on: the job list, whatever else the body carries. */
export function previewShaOf(jobs) {
  return sha256(canonicalJson(jobs))
}

function readMigrationLog(root) {
  const file = path.join(storePaths(root).dir, MIGRATION_LOG)
  if (!fs.existsSync(file)) return { version: 1, runs: [] }
  try {
    const log = JSON.parse(fs.readFileSync(file, 'utf-8'))
    if (log?.version !== 1 || !Array.isArray(log.runs)) throw new Error('unknown shape')
    return log
  } catch (e) {
    throw new StoreError(500, `${MIGRATION_LOG} is unreadable, refusing to touch it: ${e.message}`)
  }
}

/** Where the snapshot comes from (2.2 order): scored jobs, the ledger, then the browser record. */
function snapshotSources(job, jobId, { scored, ledger }) {
  const list = Array.isArray(scored?.jobs) ? scored.jobs : []
  return [
    { job: list.find((j) => j?.jobId === jobId), capturedFrom: 'scored_jobs' },
    { job: ledger?.jobs?.[jobId]?.job, capturedFrom: 'job_history' },
    { job, capturedFrom: 'browser' },
  ].filter((s) => s.job && typeof s.job === 'object' && str(s.job.title).trim() && str(s.job.company).trim())
}

/** The events one legacy record becomes. Order: applied, contact, note, follow-up, stage or outcome. */
function legacyEvents(appId, L, { at, day, appliedDay }) {
  const events = []
  const push = (type, date, data) => events.push({
    id: `${appId}:${events.length + 1}`, seq: events.length + 1, type, at, date, source: 'migration', data,
  })
  push('applied', appliedDay, {})
  if ([L.recruiterName, L.recruiterEmail, L.recruiterLinkedIn].some((v) => str(v))) {
    push('contact_added', day, {
      contactId: 'c1', role: 'recruiter', name: str(L.recruiterName), email: str(L.recruiterEmail), linkedin: str(L.recruiterLinkedIn),
    })
  }
  if (str(L.notes)) push('note_added', day, { text: str(L.notes) })
  const followUp = str(L.followUpDate)
  if (followUp && legacyDay(followUp).day === followUp) push('follow_up_set', day, { dueDate: followUp })
  const { event } = legacyStageEvent(L.interviewStage)
  if (event) push(event.type, day, event.data)
  return events
}

/**
 * Plan the migration without writing anything. `jobs` is the browser job list as posted, `store`
 * the current store, and `scored` / `ledger` the server's job files (null when absent). Pure.
 * Returns { counts, entries, applications } where `applications` are the records to add.
 */
export function planMigration(jobs, { store, settings, scored = null, ledger = null, now }) {
  const createdAt = now.toISOString()
  const board = new Set(selectableStageKeys(settings))
  const counts = { scanned: jobs.length, ignored: 0, candidates: 0, created: 0, alreadyMigrated: 0, alreadyTracked: 0, unmappable: 0 }
  const entries = []
  const applications = {}
  const seen = new Set()

  for (const [index, job] of jobs.entries()) {
    const L = legacyTrackingOf(job)
    const marked = job?.status === 'applied_manually'
    if (legacyKind(job) === 'none') {
      counts.ignored += 1
      continue
    }
    counts.candidates += 1
    const base = { index, jobId: typeof job.jobId === 'string' ? job.jobId : null, title: str(job.title), company: str(job.company) }
    const refuse = (reason) => {
      counts.unmappable += 1
      entries.push({ ...base, action: 'unmappable', reason, warnings: [] })
    }

    const problem = legacyProblem(job)
    if (problem === 'jobId is not 16 hex characters') { refuse(problem); continue }
    if (seen.has(base.jobId)) { refuse('jobId appears twice in the payload'); continue }
    seen.add(base.jobId)
    if (problem) { refuse(problem); continue }

    const appId = `mig-${base.jobId}`
    if (store.applications[appId]) {
      counts.alreadyMigrated += 1
      // Anything written to the old field after the migration is not in the store; say so.
      const changed = L ? legacyChanges(L, store.applications[appId].legacy) : []
      entries.push({
        ...base, action: 'alreadyMigrated', appId, legacyChanged: changed,
        warnings: changed.length ? [`legacy data changed since it was migrated (${changed.join(', ')}); the change is not in the store`] : [],
      })
      continue
    }
    const source = snapshotSources(job, base.jobId, { scored, ledger })[0]
    if (!source) { refuse('no source has a title and a company for this job'); continue }
    const posting = postingFromJob(source.job, base.jobId, source.capturedFrom, createdAt, true)

    const tracking = L ?? {}
    const warnings = []
    const applied = legacyDay(tracking.appliedDate)
    if (applied.bad) warnings.push(`appliedDate "${applied.bad}" is not a date; left empty (kept in legacy)`)
    else if (!applied.day) warnings.push('no applied date')
    if (!(tracking.applied === true || marked)) warnings.push('tracked but not marked applied')
    const followUp = str(tracking.followUpDate)
    if (followUp && legacyDay(followUp).day !== followUp) warnings.push(`followUpDate "${followUp}" is not YYYY-MM-DD; no follow-up event (kept in legacy)`)
    const unmapped = unmappedLegacyKeys(tracking)
    if (unmapped.length) warnings.push(`unmapped keys kept only in legacy: ${unmapped.join(', ')}`)
    const stage = legacyStageEvent(tracking.interviewStage)
    if (stage.unknown) warnings.push(`unknown interviewStage "${tracking.interviewStage}"; no stage event (kept in legacy)`)
    if (stage.event?.type === 'stage_changed' && !board.has(stage.event.data.stage)) {
      warnings.push(`target stage "${stage.event.data.stage}" is not on the board; the application shows under Unfiled`)
    }
    if (posting.descriptionMissing) warnings.push('the snapshot has no description')

    const updated = Date.parse(str(tracking.lastUpdated))
    const lastUpdated = Number.isNaN(updated) ? null : new Date(updated).toISOString()
    const at = lastUpdated ?? (applied.day ? `${applied.day}T00:00:00.000Z` : EPOCH)
    const day = lastUpdated ? localDay(new Date(lastUpdated)) : applied.day
    const events = legacyEvents(appId, tracking, { at, day, appliedDay: applied.day })

    const application = {
      id: appId,
      createdAt,
      origin: 'migration',
      posting,
      attempt: {
        channel: 'other',
        channelDetail: '',
        applicationUrl: str(tracking.applicationUrl),
        appliedDate: applied.day,
        cv: { kind: 'unknown', cvLibraryId: null, label: '', fileName: null, sha256: null },
        coverLetter: { fileName: null, sha256: null },
        previousApplicationId: null,
        distinctReason: null,
      },
      legacy: L,
      events,
    }

    const legacyOpen = !LEGACY_CLOSED_STAGES.includes(tracking.interviewStage)
    const twin = legacyOpen && Object.values(store.applications).find((app) => app.origin !== 'migration'
      && app.posting.postingKey === posting.postingKey && isActive(app) && !foldApplication(app).outcome)
    if (twin) {
      counts.alreadyTracked += 1
      entries.push({ ...base, action: 'alreadyTracked', appId: twin.id, warnings })
      continue
    }

    counts.created += 1
    applications[appId] = application
    entries.push({
      ...base, action: 'create', appId, warnings,
      capturedFrom: posting.capturedFrom, events: events.map((e) => e.type),
    })
  }
  return { counts, entries, applications }
}

/**
 * The field-level check of 6d for the records one run creates: every legacy value is in the new
 * record, and nothing else was added. Returns the problems found, [] when the migration is faithful.
 * Narrower than 6d's wording (every `mig-` record) on purpose: a record migrated earlier may
 * have gained user events since, which this check must not count against it.
 */
export function verifyMigration(jobs, plan, next, before) {
  const problems = []
  const { counts } = plan
  if (counts.candidates !== counts.created + counts.alreadyMigrated + counts.alreadyTracked + counts.unmappable) {
    problems.push('counts do not balance')
  }
  if (counts.scanned !== counts.ignored + counts.candidates) problems.push('ignored + candidates != scanned')
  const migrated = (store) => Object.values(store.applications).filter((a) => a.origin === 'migration').length
  if (migrated(next) !== migrated(before) + counts.created) problems.push('the number of migrated records is wrong')

  for (const entry of plan.entries.filter((e) => e.action === 'create')) {
    const fail = (what) => problems.push(`${entry.appId}: ${what}`)
    const app = next.applications[entry.appId]
    const job = jobs[entry.index]
    if (!app || !job) { fail('missing'); continue }
    if (!wellFormed(entry.appId, app)) fail('malformed record')
    const L = legacyTrackingOf(job)
    const T = L ?? {}
    const ofType = (type) => app.events.filter((e) => e.type === type)
    if (!sameJson(app.legacy ?? null, L ?? null)) fail('legacy differs from the original')
    if (ofType('applied').length !== 1) fail('not exactly one applied event')
    const applied = legacyDay(T.appliedDate).day
    if (app.attempt.appliedDate !== applied) fail('appliedDate differs')
    if (app.events[0].date !== applied) fail('applied event date differs')
    if (app.attempt.applicationUrl !== str(T.applicationUrl)) fail('applicationUrl differs')

    const contacts = ofType('contact_added')
    const hasContact = [T.recruiterName, T.recruiterEmail, T.recruiterLinkedIn].some((v) => str(v))
    if (contacts.length !== (hasContact ? 1 : 0)) fail('recruiter contact count differs')
    if (hasContact && (contacts[0].data.role !== 'recruiter' || contacts[0].data.name !== str(T.recruiterName)
      || contacts[0].data.email !== str(T.recruiterEmail) || contacts[0].data.linkedin !== str(T.recruiterLinkedIn))) {
      fail('recruiter contact differs')
    }
    const notes = ofType('note_added')
    if (notes.length !== (str(T.notes) ? 1 : 0) || (notes[0] && notes[0].data.text !== str(T.notes))) fail('notes differ')
    const followUps = ofType('follow_up_set')
    const wantFollowUp = str(T.followUpDate) && legacyDay(T.followUpDate).day === str(T.followUpDate)
    if (followUps.length !== (wantFollowUp ? 1 : 0) || (followUps[0] && followUps[0].data.dueDate !== str(T.followUpDate))) {
      fail('follow-up differs')
    }
    const stageEvents = app.events.filter((e) => e.type === 'stage_changed' || e.type === 'outcome_set')
    const { event } = legacyStageEvent(T.interviewStage)
    if (stageEvents.length !== (event ? 1 : 0) || (event && !sameJson({ type: stageEvents[0].type, data: stageEvents[0].data }, event))) {
      fail('interviewStage differs')
    }
    if (app.events.some((e) => e.source !== 'migration' || e.at !== app.events[0].at)) fail('event source or time differs')
    if (app.events.length !== 1 + contacts.length + notes.length + followUps.length + stageEvents.length) fail('unexpected events')
  }
  return problems
}

async function loadMigrationInput(root, body) {
  if (!body || typeof body !== 'object' || !Array.isArray(body.jobs)
    || body.jobs.some((j) => !j || typeof j !== 'object' || Array.isArray(j))) {
    throw new StoreError(400, 'Body must be { jobs: [ ... ] }, the browser job list')
  }
  const paths = storePaths(root)
  return {
    jobs: body.jobs,
    store: loadStore(root),
    settings: loadSettings(root),
    scored: readJson(paths.scored),
    ledger: readJson(paths.ledger),
  }
}

const legacyChangedOf = (plan) => plan.entries.filter((e) => e.legacyChanged?.length)
const planView = (plan, previewSha) => ({
  previewSha, counts: plan.counts, legacyChanged: legacyChangedOf(plan).length, entries: plan.entries,
})

/** Dry run: the plan and the hash that apply needs. Writes nothing. */
export function previewMigration(root, body, { now = () => new Date() } = {}) {
  return withLock(root, async () => {
    const input = await loadMigrationInput(root, body)
    const plan = planMigration(input.jobs, { ...input, now: now() })
    return { status: 200, dryRun: true, toCreate: plan.counts.created, ...planView(plan, previewShaOf(input.jobs)) }
  })
}

/**
 * Apply: refused (409) without `confirm: true` and the `previewSha` of the same job list. Order:
 * backup, plan, verify, write the store, write migration.json. A failure at any step before the
 * store write leaves the store as it was.
 */
export function migrateApplications(root, body, { now = () => new Date() } = {}) {
  return withLock(root, async () => {
    const input = await loadMigrationInput(root, body)
    if (body.confirm !== true) throw new StoreError(409, 'Run the dry run first and confirm it: send "confirm": true')
    const previewSha = previewShaOf(input.jobs)
    if (body.previewSha !== previewSha) {
      throw new StoreError(409, 'previewSha does not match this job list; run the dry run again', { previewSha })
    }
    const at = now()
    const log = readMigrationLog(root)
    const plan = planMigration(input.jobs, { ...input, now: at })

    const paths = storePaths(root)
    const dir = uniqueDir(path.join(paths.backups, `applications-${backupStamp(at)}`))
    try {
      writeFileAtomic(path.join(dir, 'legacy-jobs.json'), `${JSON.stringify(input.jobs, null, 2)}\n`)
      if (fs.existsSync(paths.store)) copyToNewFile(paths.store, path.join(dir, 'applications.json'), PRIVATE_FILE_MODE)
    } catch (e) {
      throw new StoreError(500, `Backup failed, nothing was migrated: ${e.message}`)
    }
    const backupPath = path.relative(root, dir)

    const next = { ...input.store, applications: { ...input.store.applications, ...plan.applications } }
    if (plan.counts.created) next.updatedAt = at.toISOString()
    const problems = verifyMigration(input.jobs, plan, next, input.store)
    if (problems.length) throw new StoreError(500, `Migration check failed, nothing was migrated: ${problems.join('; ')}`)

    if (plan.counts.created) saveStore(root, input.store, next)
    const run = { ranAt: at.toISOString(), previewSha, counts: plan.counts, backupPath, unmappable: plan.entries.filter((e) => e.action === 'unmappable'),
      legacyChanged: legacyChangedOf(plan).map((e) => ({ jobId: e.jobId, appId: e.appId, fields: e.legacyChanged })) }
    writeFileAtomic(path.join(paths.dir, MIGRATION_LOG), `${JSON.stringify({ version: 1, runs: [...log.runs, run].slice(-MAX_MIGRATION_RUNS) }, null, 2)}\n`)
    return { status: 200, dryRun: false, verified: true, backupPath, ...planView(plan, previewSha) }
  })
}

// --- identity hints for AI redaction ---------------------------------------------------------

/**
 * Every recruiter / contact name, e-mail and link ever recorded in the store, voided applications
 * and superseded values included (more identifiers is the safe side). ai-redact.js adds these to
 * the hints the browser sends, so a contact entered after the migration is still removed.
 * A missing store is empty; an unreadable one throws.
 */
export function knownContactIdentity(root) {
  const identity = { names: [], emails: [], phones: [], links: [] }
  const add = (list, value) => {
    if (typeof value === 'string' && value.trim() && !list.includes(value.trim())) list.push(value.trim())
  }
  for (const app of Object.values(loadStore(root).applications)) {
    for (const event of app.events) {
      if (event.type !== 'contact_added' && event.type !== 'contact_updated') continue
      add(identity.names, event.data?.name)
      add(identity.emails, event.data?.email)
      add(identity.links, event.data?.linkedin)
    }
  }
  return identity
}

// --- routes (3.1) ----------------------------------------------------------------------------

function sendJson(res, status, data) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(maskErrorField(data)))
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf-8')
        resolve(raw ? JSON.parse(raw) : {})
      } catch {
        reject(new StoreError(400, 'Body is not valid JSON'))
      }
    })
    req.on('error', reject)
  })
}

function contentTypeFor(name) {
  if (name.endsWith('.pdf')) return 'application/pdf'
  if (name.endsWith('.docx')) return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  if (name.endsWith('.html')) return 'text/html; charset=utf-8'
  if (name.endsWith('.md')) return 'text/markdown; charset=utf-8'
  return 'application/octet-stream'
}

/** The whole route table. No PUT, PATCH or DELETE: corrections are events. */
export const APPLICATION_ROUTES = [
  {
    method: 'GET',
    pattern: /^\/api\/applications$/,
    handle: async (req, res, _m, ctx) => sendJson(res, 200, loadStore(ctx.root)),
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications$/,
    handle: async (req, res, _m, ctx) => {
      const { status, ...result } = await createApplication(ctx.root, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/([^/]+)\/events$/,
    handle: async (req, res, [, id], ctx) => {
      const { status, ...result } = await appendEvent(ctx.root, id, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/([^/]+)\/move$/,
    handle: async (req, res, [, id], ctx) => {
      const { status, ...result } = await moveApplication(ctx.root, id, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/migrate\/preview$/,
    handle: async (req, res, _m, ctx) => {
      const { status, ...result } = await previewMigration(ctx.root, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/migrate$/,
    handle: async (req, res, _m, ctx) => {
      const { status, ...result } = await migrateApplications(ctx.root, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/applications\/settings$/,
    handle: async (req, res, _m, ctx) => sendJson(res, 200, readSettings(ctx.root)),
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/settings$/,
    handle: async (req, res, _m, ctx) => {
      const { status, ...result } = await changeSettings(ctx.root, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/applications\/settings\/stages$/,
    handle: async (req, res, _m, ctx) => {
      const { status, ...result } = await changeStageRegistry(ctx.root, await readJsonBody(req), ctx)
      sendJson(res, status, result)
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/applications\/([^/]+)\/files\/([^/]+)$/,
    handle: async (req, res, [, id, rawName], ctx) => {
      let name
      try {
        name = decodeURIComponent(rawName)
      } catch {
        throw new StoreError(400, 'Invalid file name')
      }
      const file = applicationFilePath(ctx.root, id, name)
      res.statusCode = 200
      res.setHeader('Content-Type', contentTypeFor(name))
      res.setHeader('Content-Disposition', `attachment; filename="${name.replace(/"/g, '_')}"`)
      fs.createReadStream(file).pipe(res)
    },
  },
]

/** Handle a request under /api/applications. Returns false for any other URL. */
export async function handleApplicationsRequest(req, res, url, { root, now } = {}) {
  if (url !== '/api/applications' && !url.startsWith('/api/applications/')) return false
  const route = APPLICATION_ROUTES.find((r) => r.method === req.method && r.pattern.test(url))
  if (!route) {
    sendJson(res, 404, { error: 'API route not found' })
    return true
  }
  try {
    await route.handle(req, res, route.pattern.exec(url), { root, ...(now ? { now } : {}) })
  } catch (e) {
    const status = e instanceof StoreError ? e.status : 500
    sendJson(res, status, { error: e.message, ...(e.extra ?? {}) })
  }
  return true
}
