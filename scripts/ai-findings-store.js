/**
 * The AI findings store (STEP5_SERVER_MASTER_PLAN section 2.8, step 2b), first slice: entity type `job`, feature `jobAnalysis`.
 * Written and read only by the Node server, called from run-ai.js.
 *
 *   data/ai/findings/                       mode 700
 *   data/ai/findings/job/<entityKey>.json   mode 600   { version, entity, findings: [ ... ] }
 *
 * Findings are only ever appended; an existing finding is never edited or removed, and a file that cannot be read is never
 * overwritten. Expiry (a feature's freshness window, if it has one) only turns a hit into a miss. A finding holds the parsed result, the cache
 * key and the input hash; the prompt itself is never stored. It holds no key, base URL, cookie or identifier (the caller checks the result
 * for identifiers first, and this module refuses text that looks like a credential). Reads and writes are synchronous,
 * so appends in one process cannot interleave; the server is the only writer.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { maskSecrets } from './secret-mask.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_ROOT = path.resolve(__dirname, '../data/ai/findings')

const DAY_MS = 24 * 60 * 60 * 1000

/** Bumped by hand when a feature's prompt or output schema changes; part of the cache key. */
export const PROMPT_VERSIONS = { jobAnalysis: '1' }

/**
 * Built-in freshness window per feature, in days, or null for no expiry; only features listed here use the store. A
 * job analysis does not age: it stays valid until a cache key input changes. A feature that does age gets a number
 * (the owner's override file, data/config/ai-findings.json, is a later step).
 */
export const DEFAULT_FRESHNESS_DAYS = { jobAnalysis: null }

export const FINDINGS_ENTITY = { jobAnalysis: 'job' }

export function usesFindings(feature) {
  return Object.hasOwn(FINDINGS_ENTITY, feature)
}

let rootOverride = null

function root() {
  return rootOverride || process.env.CAREER_OS_FINDINGS_DIR || DEFAULT_ROOT
}

export const findingsRoot = root

/** Tests point the store at a temp directory; pass nothing to restore the default. */
export function setFindingsRoot(dir) {
  rootOverride = dir || null
}

const sha256 = (text) => crypto.createHash('sha256').update(text).digest('hex')

/** JSON with sorted keys, so equal values always hash equally. */
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().filter((k) => value[k] !== undefined).map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`
  }
  return JSON.stringify(value ?? null)
}

const hashOf = (value) => sha256(canonical(value))

/** Opaque entity key of a job: the first 16 hex of sha256(jobId). No title, company or text. */
export function jobEntityKey(jobId) {
  return jobId ? sha256(String(jobId)).slice(0, 16) : null
}

/** The job fields that make up the posting itself. */
const POSTING_FIELDS = ['title', 'company', 'location', 'description']
/** The job fields that make up its scores. */
const SCORE_FIELDS = ['matchScore', 'matchLabel', 'priority', 'applyRecommendation', 'matchedSkills', 'missingSkills', 'redFlags', 'reasons', 'scoreBreakdown']

const pick = (obj, fields) => Object.fromEntries(fields.map((k) => [k, obj?.[k] ?? null]))

/**
 * What the job analysis depends on, taken from the redacted context: the posting, the job's scores, its stage and the
 * candidate profile (profile summary, intelligence summary, role strategy). Nothing else: not the AI memory (the app
 * merges every analysis into it, so it would change the key right after the call) and not the portfolio statistics.
 * Hashed separately; holds hashes only.
 */
function jobAnalysisManifest(context) {
  const job = context?.job || {}
  return {
    jobPosting: hashOf(pick(job, POSTING_FIELDS)),
    jobScores: hashOf(pick(job, SCORE_FIELDS)),
    jobStage: hashOf(job.applicationTracking ?? null),
    profile: hashOf({ profile: context?.profile ?? null, intelligenceSummary: context?.intelligenceSummary ?? null, roleStrategy: context?.roleStrategy ?? null }),
  }
}

/** The cache key `model|promptVersion|inputHash`; the input hash covers the manifest above. A prompt change is a PROMPT_VERSIONS bump. */
export function buildCacheKey({ feature, model, context }) {
  const inputHash = hashOf(jobAnalysisManifest(context))
  const promptVersion = PROMPT_VERSIONS[feature]
  return { inputHash, promptVersion, cacheKey: `${model || ''}|${promptVersion}|${inputHash}` }
}

function entityFile(entityType, entityKey) {
  return path.join(root(), entityType, `${entityKey}.json`)
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  if ((fs.statSync(dir).mode & 0o777) !== 0o700) fs.chmodSync(dir, 0o700)
}

function writeAtomic(file, text) {
  const dir = path.dirname(file)
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`)
  let fd
  try {
    fd = fs.openSync(tmp, 'wx', 0o600)
    fs.fchmodSync(fd, 0o600)
    fs.writeSync(fd, text)
    fs.fsyncSync(fd)
    fs.closeSync(fd)
    fd = undefined
    fs.renameSync(tmp, file)
  } catch (e) {
    if (fd !== undefined) {
      try { fs.closeSync(fd) } catch { /* already closed */ }
    }
    try { fs.unlinkSync(tmp) } catch { /* never created */ }
    throw e
  }
}

/** { record } (null when the file does not exist) or { unreadable: true }. */
function readRecord(file) {
  let text
  try {
    text = fs.readFileSync(file, 'utf-8')
  } catch (e) {
    return e.code === 'ENOENT' ? { record: null } : { unreadable: true }
  }
  try {
    const parsed = JSON.parse(text)
    if (parsed?.version === 1 && Array.isArray(parsed.findings)) return { record: parsed }
  } catch { /* unreadable: handled below */ }
  return { unreadable: true }
}

/** Throws unless `next` is `prev` with findings added at the end (seq 1..n, ids unchanged). */
export function assertAppendOnly(prev, next) {
  const before = prev?.findings || []
  const after = next.findings
  if (after.length < before.length) throw new Error('findings store: a finding was removed')
  before.forEach((f, i) => {
    if (canonical(f) !== canonical(after[i])) throw new Error('findings store: a finding was edited')
  })
  after.forEach((f, i) => {
    if (f.seq !== i + 1) throw new Error('findings store: seq is not 1..n')
  })
}

/**
 * Looks for a fresh finding with this cache key. { hit: true, finding } or { hit: false, reason }, reason one of
 * none | stale | unreadable. Never throws, never writes, never deletes.
 */
export function lookupFinding({ feature, entityKey, cacheKey, now = Date.now(), freshnessDays = DEFAULT_FRESHNESS_DAYS[feature] }) {
  try {
    const read = readRecord(entityFile(FINDINGS_ENTITY[feature], entityKey))
    if (read.unreadable) return { hit: false, reason: 'unreadable' }
    const matching = (read.record?.findings || []).filter((f) => f.cacheKey === cacheKey)
    if (!matching.length) return { hit: false, reason: 'none' }
    const fresh = freshnessDays == null ? matching : matching.filter((f) => now - Date.parse(f.at) <= freshnessDays * DAY_MS)
    return fresh.length ? { hit: true, finding: fresh[fresh.length - 1] } : { hit: false, reason: 'stale' }
  } catch {
    return { hit: false, reason: 'unreadable' }
  }
}

/**
 * Appends one finding. { stored: true, finding } or { stored: false, reason }. Text that looks like a credential is not
 * stored, and a record that cannot be read is left as it is. Never throws.
 */
export function appendFinding({ feature, entityKey, provider, model, promptVersion, inputHash, cacheKey, result, now = new Date() }) {
  try {
    const entityType = FINDINGS_ENTITY[feature]
    const body = JSON.stringify(result)
    if (maskSecrets(body) !== body) return { stored: false, reason: 'credential-like text' }
    const file = entityFile(entityType, entityKey)
    const read = readRecord(file)
    if (read.unreadable) return { stored: false, reason: 'unreadable' }
    const prev = read.record
    const seq = (prev?.findings.length || 0) + 1
    const finding = {
      id: `${entityKey}:${seq}`,
      seq,
      at: now.toISOString(),
      feature,
      provider: provider || '',
      model: model || '',
      promptVersion,
      inputHash,
      cacheKey,
      finding: result,
      source: 'model',
    }
    const next = prev
      ? { ...prev, findings: [...prev.findings, finding] }
      : { version: 1, entity: { type: entityType, key: entityKey }, findings: [finding] }
    assertAppendOnly(prev, next)
    ensureDir(root())
    ensureDir(path.dirname(file))
    writeAtomic(file, `${JSON.stringify(next, null, 2)}\n`)
    return { stored: true, finding }
  } catch (e) {
    return { stored: false, reason: maskSecrets(e.message) }
  }
}
