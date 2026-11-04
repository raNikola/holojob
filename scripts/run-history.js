/**
 * GET /api/runs (S7a): the run records, read-only, slim and bounded.
 *
 * What it does not do: take a lock, start a process, repair or mark anything, read the ledger, staging, an event log or an ad.
 * It reads the names in data/analytics/runs/ and up to `limit` record files there, and (only when a record says running) the lock
 * file's inode and /proc/locks, to tell a live run from a dead record. Nothing is written.
 *
 * What it returns is built field by field from an allow-list (`project`). The raw record is never returned, so a field a later slice
 * adds to a record, or a message that carries more than it should, cannot reach the browser by accident. Every text goes through
 * `text()` (secrets masked, links, e-mail addresses and phone-like numbers replaced, length capped), and a message is shown whole only if
 * it is the app's own fixed wording (`message`, `errorSummary`); text from outside the app is summarised, never copied.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { maskSecrets } from './secret-mask.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')

export const DEFAULT_LIMIT = 30
export const MAX_LIMIT = 100
export const RETENTION_DAYS = 90
const MAX_RECORD_BYTES = 256 * 1024
const MAX_ISSUES = 10
const MAX_SOURCES = 20
const MAX_BOARDS = 60
const MAX_TEXT = 300
const RECORD_NAME = /^\d{8}T\d{6}Z-[0-9A-Za-z]{1,32}\.json$/
const RUN_ID = /^[0-9A-Za-z]{1,32}$/
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,40}$/
const BOARD = /^[A-Za-z0-9][A-Za-z0-9_. -]{0,59}$/
const CODE = /^[a-z][a-z_]{0,39}$/
const TRIGGERS = ['manual', 'pipeline', 'scheduled']
const RUN_STATUSES = ['ok', 'partial', 'failed', 'skipped', 'running', 'interrupted', 'cancelled']
const SOURCE_STATUSES = ['ok', 'partial', 'failed', 'skipped']
const STEP_NAMES = ['discovery', 'scoring']
const CANCEL_OUTCOMES = ['collected_ads_saved', 'stopped_nothing_imported', 'imported_before_cancel', 'finished_before_cancel']
const IMPORT_KINDS = ['complete', 'partial', 'nothing', 'refused']
const MAX_EVENTS = 200
const MAX_EVENT_LOG_BYTES = 1024 * 1024
const EVENT_TYPES = [
  'run_start', 'run_end', 'step_start', 'step_end', 'step_skipped', 'source_start', 'source_end', 'commit_start', 'commit_end', 'commit_incomplete',
  'error', 'interrupted', 'cancel_requested', 'cancel_signal', 'cancel_kill', 'scrape_stopped', 'cancelled',
]

/** The codes the screen has a text for (src/data/proofReasons.json, the file the Python side is tested against). */
const reasonTable = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/data/proofReasons.json'), 'utf-8'))
export const KNOWN_PROOF_CODES = new Set(Object.keys(reasonTable))

function runsDir() {
  return path.join(process.env.HOLOJOB_ANALYTICS_DIR || path.join(ROOT, 'data/analytics'), 'runs')
}

function lockPath() {
  return process.env.HOLOJOB_PIPELINE_LOCK || path.join(ROOT, 'data/jobs/.pipeline.lock')
}

// --- cleaning ----------------------------------------------------------------------------------------------------------------

/** A text from a record, made safe to send: masked, no link, no e-mail address, no phone-like number, one line, capped. */
export function text(value, max = MAX_TEXT) {
  if (typeof value !== 'string') return null
  const cleaned = maskSecrets(value)
    .replace(/\bhttps?:\/\/\S+/gi, '[link]')
    .replace(/\bwww\.\S+/gi, '[link]')
    .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, '[email]')
    .replace(/\+\d[\d ()-]{6,}\d/g, '[number]')
    .replace(/\b\d{3}[ -]\d{3}[ -]\d{3,4}\b/g, '[number]')
    .replace(/\p{Cc}+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned.length > max ? `${cleaned.slice(0, max - 1)}…` : cleaned
}

// --- messages ------------------------------------------------------------------------------------------------------------------
//
// A record's messages come from this app's own wording, but many end in text from outside it: an exception, a step's output, a
// provider's error. That text can hold anything, including an ad title, and no pattern can promise otherwise. So a message is shown
// whole only if it is one of the app's own fixed texts (counts, names and ids in them); a known beginning keeps the app's words and
// summarises the rest; any other text is summarised. A summary holds only exception class names, an HTTP status and snake_case codes.

const WHOLE = [
  /^0 ads kept \((?:read \d+, all filtered out|read 0)\); nothing was closed for this source$/,
  /^Every source was skipped: no source searched in this run$/,
  /^No source gave a usable result, so nothing was imported and the job list was not changed\.$/,
  /^(?:discovery|scoring) failed with exit code -?\d+/, // a step's output tail follows the colon and is cut (see `message`)
  /^Run \w+ left an incomplete save of the job files\. Written: [^.]*\. Not written: [^.]*\. They may not match each other\. Nothing was repaired\.$/,
  /^A save of the job files did not finish \(its marker is unreadable\); they may not match each other\. Nothing was repaired\.$/,
  /^The run did not finish: it stopped(?: during \w+)? \(killed, or the server restarted\)\. It was not resumed\.$/,
  /^discovered_jobs\.json would hold \d+ rows \(more than \d+\); nothing is dropped for it$/,
  /^Cancelled\. (?:\d+ collected ads were saved|No ads were saved)\. Nothing else changed\. Scoring was skipped\.$/,
  /^Cancelled\. The scrape had to be stopped hard: nothing was imported and no job changed\. Scoring was skipped\.$/,
  /^The cancel came after the import was committed, so the scrape counts as any run\. Scoring was skipped; Re-score runs it\.$/,
  /^board [\w.-]{1,60} answered with 0 ads; its open ads were kept$/,
  /^Ashby board [\w.-]{1,60}: paging field in the answer: \w+$/,
  /^\d+ ads left for the next run \(cap of \d+ details\)$/,
  /^No jobSpySearchTerms found in intelligence file\.$/,
  /^Infostud covers Serbia only, not '[^']{0,60}'$/,
  /^Joberty lists no ads for '[^']{0,60}'$/,
  /^Wellfound is not built yet$/,
]
const PREFIXES = [
  'Staging failed, so this run is not fully saved: ', 'An old commit marker could not be removed: ',
  'Commit marker not written, so a stop during this save would go unnoticed: ',
  'Commit marker not removed, so the next run will report this save as incomplete: ', 'Discovery stopped: ', 'The run stopped: ',
  'The job list is out of date and could not be rebuilt: ', 'Nothing was imported: staging failed ', 'The import stopped while writing: ',
  'Import refused: ', 'The run was cancelled but its staging could not be marked, so nothing was imported: ',
  "The cancelled run's staging could not be marked, so it is not safe to import it as a proven run: ", 'No valid providers resolved from: ',
  'The ledger as it was before this run could not be kept: ', 'The discovered file as it was before this run could not be kept: ',
  'Discard reasons are not recorded for this run', 'Staging is off for this run', 'Staging for ',
]

/** Exception class names, an HTTP status and snake_case codes found in a text; nothing else of it. */
export function summarise(value) {
  const found = []
  const raw = typeof value === 'string' ? value : ''
  for (const match of raw.matchAll(/\b([A-Z][A-Za-z]{2,40}(?:Error|Exception|Timeout))\b/g)) found.push(match[1])
  for (const match of raw.matchAll(/\b(?:HTTP\w*|status(?: code)?)[ :]*(\d{3})\b/gi)) found.push(`HTTP ${match[1]}`)
  for (const match of raw.matchAll(/\b([a-z]{2,15}(?:_[a-z]{2,15}){1,4})\b/g)) if (!/key|token|secret|pass|auth|cookie/.test(match[1])) found.push(match[1])
  const unique = [...new Set(found)].slice(0, 6)
  return unique.length ? `details withheld (${unique.join(', ')})` : 'details withheld'
}

/** An issue or step message as it may be shown. */
export function message(value) {
  const cleaned = text(value)
  if (cleaned === null) return null
  if (WHOLE.some((pattern) => pattern.test(cleaned))) return cleaned.replace(/^((?:discovery|scoring) failed with exit code -?\d+).*$/, '$1')
  const prefix = PREFIXES.find((one) => cleaned.startsWith(one))
  return prefix ? `${prefix.replace(/[:\s]+$/, '')}: ${summarise(cleaned.slice(prefix.length))}` : `Message ${summarise(cleaned)}`
}

/** A source's error: its parts are `board: error` pairs; each error is summarised, each board name kept if it is a plain name. */
export function errorSummary(value) {
  const cleaned = text(value, 600)
  if (cleaned === null) return null
  return cleaned.split('; ').slice(0, 20).map((part) => {
    const match = /^([\w.-]{1,60}): (.*)$/s.exec(part)
    const summary = summarise(part)
    return match ? `${match[1]}: ${summarise(match[2])}` : `${summary[0].toUpperCase()}${summary.slice(1)}`
  }).join('; ')
}

const count = (value) => (Number.isSafeInteger(value) && value >= 0 && value < 1e9 ? value : null)
const pick = (value, allowed, fallback = null) => (allowed.includes(value) ? value : fallback)
const name = (value) => (typeof value === 'string' && NAME.test(value) ? value : null)
const time = (value) => (typeof value === 'string' && value.length <= 40 && !Number.isNaN(Date.parse(value)) ? value : null)
const seconds = (from, to) => (from && to && Date.parse(to) >= Date.parse(from) ? Math.round((Date.parse(to) - Date.parse(from)) / 1000) : null)
/** Only codes the shared file knows; anything else is shown as no code, never as free text. */
const codes = (value) => (Array.isArray(value) ? [...new Set(value.filter((c) => typeof c === 'string' && KNOWN_PROOF_CODES.has(c)))].slice(0, 8) : [])

// --- liveness ----------------------------------------------------------------------------------------------------------------

/**
 * Does any process hold the pipeline lock? Read from /proc/locks, matched on the inode alone (as python/run_rescrape.py does; the device
 * column can differ across a bind mount). Takes nothing and starts nothing. null when it cannot be told, which callers read as "alive".
 */
export function lockIsHeld({ lock = lockPath(), procLocks = '/proc/locks' } = {}) {
  let inode
  try {
    inode = fs.statSync(lock).ino
  } catch (error) {
    return error.code === 'ENOENT' ? false : null
  }
  let rows
  try {
    rows = fs.readFileSync(procLocks, 'utf-8').split('\n')
  } catch {
    return null
  }
  for (const row of rows) {
    const parts = row.trim().split(/\s+/)
    if (parts.length > 5 && parts.includes('FLOCK') && Number(parts[5].split(':').pop()) === inode) return true
  }
  return false
}

// --- the allow-list ------------------------------------------------------------------------------------------------------------

/** A provider's own words for why a board is not complete ("the answer reports 9 postings and 8 were read"): fixed phrases and numbers only. */
function boardDetail(value) {
  const cleaned = text(value, 160)
  return cleaned !== null && /^[a-z][a-z0-9 ,()'-]*$/i.test(cleaned) && !/https?:|@/.test(cleaned) ? cleaned : null
}

function projectProof(entry) {
  if (!entry || typeof entry !== 'object' || !entry.proof || typeof entry.proof !== 'object') return { state: 'not_recorded', codes: [], boards: [] }
  const proof = entry.proof
  const boards = (Array.isArray(proof.boards) ? proof.boards : []).slice(0, MAX_BOARDS).flatMap((row) => {
    if (!row || typeof row !== 'object' || typeof row.board !== 'string') return []
    return [{ board: BOARD.test(row.board) ? row.board : '[board]', state: row.proven === true ? 'proven' : 'not_proven', codes: codes(row.why), detail: boardDetail(row.detail) }]
  })
  return { state: proof.proven === true ? 'proven' : 'not_proven', codes: codes(proof.why), boards }
}

function projectFilterReasons(entry) {
  const found = entry?.filterReasons
  if (!found || typeof found !== 'object' || Array.isArray(found)) return null
  const out = {}
  for (const [reason, number] of Object.entries(found).slice(0, 13)) {
    if (CODE.test(reason) && count(number) !== null) out[reason] = number
  }
  return out
}

function projectSource(source, imported) {
  const entry = (imported?.sources ?? []).find((one) => one && one.name === source.name)
  const returned = count(source.read)
  const collected = count(source.kept)
  const started = time(source.startedAt)
  const finished = time(source.finishedAt)
  return {
    name: name(source.name) ?? '?',
    status: pick(source.status, [...SOURCE_STATUSES, 'unfinished'], 'unknown'),
    returned,
    collected,
    filteredOut: returned !== null && collected !== null && returned >= collected ? returned - collected : null,
    new: count(source.new),
    error: errorSummary(source.error),
    skipReason: source.skipReason === null || source.skipReason === undefined ? null : message(source.skipReason),
    boardsFailed: (Array.isArray(source.boardsFailed) ? source.boardsFailed : []).slice(0, 20).map((b) => (typeof b === 'string' && BOARD.test(b) ? b : '[board]')),
    startedAt: started,
    finishedAt: finished,
    durationSeconds: seconds(started, finished),
    proof: imported ? projectProof(entry) : { state: 'not_recorded', codes: [], boards: [] },
    filterReasons: imported ? projectFilterReasons(entry) : null,
  }
}

function projectImport(imported) {
  if (!imported || typeof imported !== 'object') return null
  const ledger = imported.ledger && typeof imported.ledger === 'object' ? imported.ledger : null
  return {
    kind: pick(imported.kind, IMPORT_KINDS, 'unknown'),
    complete: imported.complete === true,
    saved: count(imported.saved),
    new: count(imported.new),
    refreshed: count(imported.refreshed),
    duplicatesRemoved: count(imported.duplicatesRemoved),
    crosspostsMerged: count(imported.crosspostsMerged),
    rejected: count(imported.rejected),
    ledger: ledger ? Object.fromEntries(['closed', 'absent', 'reopened', 'changed', 'known'].map((key) => [key, count(ledger[key])])) : null,
    nothingSaved: typeof imported.nothingSaved === 'string' && CODE.test(imported.nothingSaved) ? imported.nothingSaved : null,
  }
}

/**
 * One record as the API shows it. `alive` is the answer for a record that says running (true: a run holds the lock; false: nobody
 * does, so the record is a dead run's and is shown as interrupted, with `inferred`; nothing is written either way).
 */
export function project(record, { alive = true, cancelRequested = false } = {}) {
  if (!record || typeof record !== 'object' || typeof record.runId !== 'string' || !RUN_ID.test(record.runId)) return null
  const recorded = pick(record.status, RUN_STATUSES, 'unknown')
  const inferred = recorded === 'running' && alive === false
  const status = inferred ? 'interrupted' : recorded
  const startedAt = time(record.startedAt)
  const finishedAt = time(record.finishedAt)
  const imported = projectImport(record.import)
  const sourcesRaw = (Array.isArray(record.sources) ? record.sources : []).filter((one) => one && typeof one === 'object').slice(0, MAX_SOURCES)
  const importBlock = record.import && typeof record.import === 'object' ? record.import : null
  const sources = sourcesRaw.map((one) => projectSource(one, importBlock))
  // A source the import knows but the record has no row for never reported (the run was cancelled or killed while it was read).
  for (const entry of (Array.isArray(importBlock?.sources) ? importBlock.sources : []).slice(0, MAX_SOURCES)) {
    if (entry && typeof entry.name === 'string' && !sourcesRaw.some((one) => one.name === entry.name) && sources.length < MAX_SOURCES) {
      sources.push({ ...projectSource({ name: entry.name, status: 'unfinished' }, importBlock), status: 'unfinished' })
    }
  }
  const sum = (key) => (sources.length && sources.every((one) => one[key] !== null) ? sources.reduce((total, one) => total + one[key], 0) : null)
  const cancel = record.cancel && typeof record.cancel === 'object' ? record.cancel : null
  const issues = (Array.isArray(record.issues) ? record.issues : []).filter((one) => one && typeof one === 'object')
  return {
    runId: record.runId,
    trigger: pick(record.trigger, TRIGGERS, 'unknown'),
    status,
    inferred,
    startedAt,
    finishedAt,
    durationSeconds: status === 'running' ? null : seconds(startedAt, finishedAt),
    steps: (Array.isArray(record.steps) ? record.steps : []).slice(0, 4).map((step) => ({
      name: pick(step?.name, STEP_NAMES, '?'),
      status: pick(step?.status, [...RUN_STATUSES, 'running'], 'unknown'),
      exitCode: Number.isInteger(step?.exitCode) && Math.abs(step.exitCode) < 256 ? step.exitCode : null,
    })),
    canCancel: record.orchestrator === 'rescrape' && status === 'running',
    cancelRequested: Boolean(cancelRequested) && status === 'running',
    cancel: cancel ? { requestedAt: time(cancel.requestedAt), outcome: pick(cancel.outcome, CANCEL_OUTCOMES, 'unknown'), saved: count(cancel.saved) } : null,
    counts: {
      returned: sum('returned'),
      filteredOut: sum('filteredOut'),
      collected: sum('collected'),
      saved: imported ? imported.saved : null,
      new: imported ? imported.new : null,
      refreshed: imported ? imported.refreshed : null,
    },
    import: imported,
    sources,
    issuesCount: issues.length,
    issues: issues.slice(0, MAX_ISSUES).map((issue) => ({
      level: pick(issue.level, ['error', 'warning'], 'warning'),
      source: name(issue.source),
      message: message(issue.message) ?? '',
    })),
    staging: { ok: typeof record.staging?.ok === 'boolean' ? record.staging.ok : null },
    incompleteCommit: Boolean(record.incompleteCommit),
    recorded: { import: imported !== null, sourceTimes: sources.some((one) => one.startedAt !== null) },
  }
}

// --- the query and the list ----------------------------------------------------------------------------------------------------

/** `?limit=` and `?before=`. A limit past the maximum is the maximum; anything else wrong is a 422 naming the field. */
export function parseQuery(params) {
  const rawLimit = params.get('limit')
  let limit = DEFAULT_LIMIT
  if (rawLimit !== null) {
    if (!/^\d{1,6}$/.test(rawLimit) || Number(rawLimit) < 1) return { error: 'limit' }
    limit = Math.min(Number(rawLimit), MAX_LIMIT)
  }
  const before = params.get('before')
  if (before !== null && !RECORD_NAME.test(before)) return { error: 'before' }
  return { limit, before }
}

/** GET /api/runs. Returns { status, body }. */
export function listRuns(params = new URLSearchParams(), options = {}) {
  const { dir = runsDir(), lock = lockIsHeld } = options
  const query = parseQuery(params)
  if (query.error) return { status: 422, body: { ok: false, error: 'invalid', field: query.error } }
  let names
  try {
    names = fs.readdirSync(dir)
  } catch {
    names = []
  }
  const present = new Set(names)
  const records = names.filter((n) => RECORD_NAME.test(n)).sort().reverse().filter((n) => !query.before || n < query.before)
  const page = records.slice(0, query.limit)
  const next = records.length > page.length ? page[page.length - 1] : null

  const parsed = []
  let skipped = 0
  for (const file of page) {
    try {
      const full = path.join(dir, file)
      if (fs.statSync(full).size > MAX_RECORD_BYTES) throw new Error('too large')
      parsed.push({ file, record: JSON.parse(fs.readFileSync(full, 'utf-8')) })
    } catch {
      skipped += 1
    }
  }
  const alive = parsed.some(({ record }) => record?.status === 'running') ? lock() !== false : true
  const runs = []
  for (const { file, record } of parsed) {
    const shown = project(record, { alive, cancelRequested: present.has(file.replace(/\.json$/, '.cancel')) })
    if (shown) runs.push(shown)
    else skipped += 1
  }
  const active = query.before ? null : runs.find((run) => run.status === 'running')
  return { status: 200, body: { ok: true, runs, next, skipped, retentionDays: RETENTION_DAYS, activeRunId: active?.runId ?? null } }
}


// --- one run, live (S7c) ---------------------------------------------------------------------------------------------------------

/**
 * One event as the screen may see it, from an allow-list. A message is shown whole only if it is the app's own fixed text (`message`);
 * an error or a skip reason is summarised like the same fields of a source. The event log holds more (file lists, run ids); none of it is
 * returned.
 */
export function projectEvent(event) {
  if (!event || typeof event !== 'object') return null
  const status = pick(event.status, [...RUN_STATUSES, 'running'], null)
  return {
    type: pick(event.type, EVENT_TYPES, 'unknown'),
    at: time(event.at),
    step: pick(event.step, STEP_NAMES, null),
    source: name(event.source),
    status,
    read: count(event.read),
    kept: count(event.kept),
    saved: count(event.saved),
    sourcesDone: count(event.sourcesDone),
    exitCode: Number.isInteger(event.exitCode) && Math.abs(event.exitCode) < 256 ? event.exitCode : null,
    error: errorSummary(event.error),
    skipReason: event.skipReason === null || event.skipReason === undefined ? null : message(event.skipReason),
    message: typeof event.message === 'string' ? message(event.message) : null,
  }
}

/** The complete lines of an event log from line `after` on, at most MAX_EVENTS. A torn last line is not read yet; a bad line is skipped but counted. */
export function readEvents(file, after = 0) {
  let raw
  try {
    if (fs.statSync(file).size > MAX_EVENT_LOG_BYTES) return { events: [], next: after }
    raw = fs.readFileSync(file, 'utf-8')
  } catch {
    return { events: [], next: 0 }
  }
  const lines = raw.split('\n')
  lines.pop() // what follows the last newline: nothing, or a torn line
  const slice = lines.slice(after, after + MAX_EVENTS)
  const events = []
  for (const line of slice) {
    try {
      const shown = projectEvent(JSON.parse(line))
      if (shown) events.push(shown)
    } catch {
      // a line torn by a killed writer still counts towards the cursor
    }
  }
  return { events, next: after + slice.length }
}

/**
 * GET /api/runs/<runId>?after=N: one run (the same allow-list as the list) and its events from the cursor. Node only: no lock, no process,
 * no recovery, no write. A running record nobody holds the lock for is returned as interrupted with `inferred: true`, and nothing is marked.
 */
export function getRun(runId, params = new URLSearchParams(), options = {}) {
  const { dir = runsDir(), lock = lockIsHeld } = options
  if (typeof runId !== 'string' || !RUN_ID.test(runId)) return { status: 422, body: { ok: false, error: 'invalid', field: 'runId' } }
  const rawAfter = params.get('after')
  if (rawAfter !== null && !/^\d{1,9}$/.test(rawAfter)) return { status: 422, body: { ok: false, error: 'invalid', field: 'after' } }
  const after = rawAfter === null ? 0 : Number(rawAfter)
  let names
  try {
    names = fs.readdirSync(dir)
  } catch {
    names = []
  }
  const file = names.filter((n) => RECORD_NAME.test(n) && n.endsWith(`-${runId}.json`)).sort().pop()
  if (!file) return { status: 404, body: { ok: false, error: 'unknown_run', message: 'There is no such run.' } }
  let record
  try {
    const full = path.join(dir, file)
    if (fs.statSync(full).size > MAX_RECORD_BYTES) throw new Error('too large')
    record = JSON.parse(fs.readFileSync(full, 'utf-8'))
  } catch {
    return { status: 404, body: { ok: false, error: 'unreadable_run', message: 'This run\'s record cannot be read.' } }
  }
  const alive = record?.status === 'running' ? lock() !== false : true
  const run = project(record, { alive, cancelRequested: names.includes(file.replace(/\.json$/, '.cancel')) })
  if (!run || run.runId !== runId) return { status: 404, body: { ok: false, error: 'unreadable_run', message: 'This run\'s record cannot be read.' } }
  const { events, next } = readEvents(path.join(dir, file.replace(/\.json$/, '.events.jsonl')), after)
  return { status: 200, body: { ok: true, run, events, next, active: run.status === 'running' } }
}
