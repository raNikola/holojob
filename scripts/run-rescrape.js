/**
 * The background Re-scrape, Node side: start it, read its status. python/run_rescrape.py does the work and holds the lock.
 *
 * Node cannot flock, so every question about the lock goes to `run_rescrape.py reconcile` or `hold`. Node writes the mirrors the
 * browser sends, starts the orchestrator in its own session with no pipe back, and never signals a process: closing the tab
 * or restarting Node does not stop a run, and reading its status needs only the files in data/analytics/runs/.
 */

import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeIntelligenceFile } from './save-intelligence.js'
import { writeProfileFile } from './save-profile.js'
import { maskSecrets } from './secret-mask.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/run_rescrape.py')
const INTELLIGENCE_PATH = path.join(ROOT, 'data/intelligence/candidate-intelligence.json')
const JOBS_PATH = path.join(ROOT, 'data/jobs/discovered_jobs.json')
const SCORED_PATH = path.join(ROOT, 'data/jobs/scored_jobs.json')

const EXIT_LOCKED = 75
const RECORD_NAME = /^\d{8}T\d{6}Z-([^/]+)\.json$/
const COMMIT_MARKER = '.commit-in-progress.json'
const PROVIDERS = /^[a-z0-9][a-z0-9_-]*(,[a-z0-9][a-z0-9_-]*)*$/i
const MAX_COUNTRY_CHARS = 100
const START_WAIT_MS = 15000
const START_POLL_MS = 50

export const RUN_ACTIVE = {
  ok: false,
  error: 'run_active',
  message: 'A job run is in progress (Re-scrape, scoring or pipeline); nothing started. Try again when it has finished.',
}

/** A scripted run's HTTP status: exit code 75 means another run holds the lock. */
export function runHttpStatus(result) {
  if (result.ok) return 200
  return result.exitCode === EXIT_LOCKED ? 409 : 500
}

function runsDir() {
  return path.join(process.env.HOLOJOB_ANALYTICS_DIR || path.join(ROOT, 'data/analytics'), 'runs')
}

function cli(command, { python = VENV_PYTHON, script = SCRIPT, spawnFn = spawn } = {}) {
  return new Promise((resolve, reject) => {
    const out = []
    const child = spawnFn(python, [script, command], { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] })
    child.stdout.on('data', (d) => out.push(d))
    child.on('error', reject)
    child.on('close', (code) => resolve({ code, stdout: Buffer.concat(out).toString('utf-8') }))
  })
}

/** Is a run alive? Marks dead `running` records interrupted on the way (Python, holding the lock). Rejects when it cannot tell. */
export async function reconcileRuns(options) {
  const { code, stdout } = await cli('reconcile', options)
  if (code !== 0) throw new Error(`reconcile exited ${code}`)
  return JSON.parse(stdout.trim().split('\n').pop())
}

/** For the routes that write the mirrors before their run: true only when a run is known to hold the lock. Their script checks again. */
export async function isRunBusy(options) {
  try {
    return (await reconcileRuns(options)).busy
  } catch {
    return false
  }
}

/** Run `action` holding the lock. Answers { busy: true } without running it when a run holds the lock. Rejects when it cannot tell. */
export function withRunLock(action, { python = VENV_PYTHON, script = SCRIPT, spawnFn = spawn } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawnFn(python, [script, 'hold'], { cwd: ROOT, stdio: ['pipe', 'pipe', 'ignore'] })
    let locked = false
    let finished = null
    let output = ''
    const unknown = (message) => Object.assign(new Error(message), { lockUnknown: true })
    child.on('error', () => reject(unknown('lock helper did not start')))
    child.stdout.on('data', async (chunk) => {
      output += chunk.toString()
      if (locked || !output.includes('locked')) return
      locked = true
      try {
        finished = { value: { busy: false, value: await action() } }
      } catch (error) {
        finished = { error }
      }
      child.stdin.end() // the lock goes when the helper sees this, or when this process dies
    })
    child.on('close', (code) => {
      if (finished?.error) reject(finished.error)
      else if (finished) resolve(finished.value)
      else if (code === EXIT_LOCKED) resolve({ busy: true })
      else reject(unknown(`lock helper exited ${code}`))
    })
  })
}

/** Reconcile when the server starts: a run that died with the last server is reported, not resumed. Never fails the start. */
export async function reconcileOnStart(options) {
  try {
    await reconcileRuns(options)
  } catch {
    // no venv in this checkout, or the data folder is missing: there is nothing to reconcile
  }
}

function writeRequestMirrors(body) {
  if (body.intelligence) writeIntelligenceFile(body.intelligence)
  else if (!fs.existsSync(INTELLIGENCE_PATH)) return `Missing ${INTELLIGENCE_PATH}. Generate intelligence in Module 2 first.`
  if (body.profile) writeProfileFile(body.profile)
  return null
}

function recordExists(runId) {
  try {
    return fs.readdirSync(runsDir()).some((name) => RECORD_NAME.exec(name)?.[1] === runId)
  } catch {
    return false
  }
}

let starting = false

/** POST /api/rescrape. Answers once the orchestrator holds the lock and its record is on disk, or has refused. */
export async function startRescrape(body = {}, options = {}) {
  const { reconcile = reconcileRuns, writeMirrors = writeRequestMirrors, spawnFn = spawn, python = VENV_PYTHON, script = SCRIPT } = options
  const providers = body.providers ?? 'serbia'
  const country = body.country ?? ''
  if (typeof providers !== 'string' || !PROVIDERS.test(providers)) return { status: 422, body: { ok: false, error: 'invalid', field: 'providers' } }
  if (typeof country !== 'string' || country.length > MAX_COUNTRY_CHARS) return { status: 422, body: { ok: false, error: 'invalid', field: 'country' } }
  if (starting) return { status: 409, body: RUN_ACTIVE }
  starting = true
  try {
    let state
    try {
      state = await reconcile({ python, script, spawnFn })
    } catch {
      return { status: 503, body: { ok: false, error: 'no_python', message: 'The job tools are not set up on the server, so nothing started.' } }
    }
    // Before the mirrors: a request that is refused must not change an active run's input.
    if (state.busy) return { status: 409, body: RUN_ACTIVE }
    const missing = writeMirrors(body)
    if (missing) return { status: 422, body: { ok: false, error: 'no_intelligence', message: missing } }

    const runId = randomBytes(6).toString('hex')
    const args = [script, 'start', '--run-id', runId, '--providers', providers, ...(country ? ['--country', country] : [])]
    // Its own session and no pipes: nothing that happens to this process or the browser can reach the run.
    const child = spawnFn(python, args, { cwd: ROOT, detached: true, stdio: 'ignore', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    return await new Promise((resolve) => {
      let answered = false
      const answer = (reply) => {
        if (answered) return
        answered = true
        clearInterval(timer)
        resolve(reply)
      }
      const started = Date.now()
      const timer = setInterval(() => {
        if (recordExists(runId)) answer({ status: 202, body: { ok: true, runId } })
        else if (Date.now() - started > START_WAIT_MS) answer({ status: 504, body: { ok: false, error: 'no_answer', message: 'The run did not confirm its start. Reload to see whether it is running.' } })
      }, START_POLL_MS)
      child.on('error', () => answer({ status: 500, body: { ok: false, error: 'failed', message: 'The run could not be started.' } }))
      child.on('exit', (code) => {
        if (code === EXIT_LOCKED) answer({ status: 409, body: RUN_ACTIVE })
        else {
          answer(recordExists(runId) && code === 0 ? { status: 202, body: { ok: true, runId } } : { status: 500, body: { ok: false, error: 'failed', message: `The run stopped at once (exit code ${code}).` } })
          reconcile({ python, script, spawnFn }).catch(() => {}) // a crash that skipped the orchestrator's own ending shows as interrupted
        }
      })
      child.unref?.()
    })
  } finally {
    starting = false
  }
}

/** The complete lines of an event log from line `after` on. A last line with no newline is not read yet; an unparsable line is skipped. */
export function readEventsFile(file, after = 0) {
  let text
  try {
    text = fs.readFileSync(file, 'utf-8')
  } catch {
    return { events: [], next: 0 }
  }
  const lines = text.split('\n')
  lines.pop() // what follows the last newline: nothing, or a torn line
  const events = []
  for (const line of lines.slice(after)) {
    try {
      events.push(JSON.parse(line))
    } catch {
      // torn by a killed writer; the line count still includes it, so the cursor stays right
    }
  }
  return { events, next: lines.length }
}

function latestRecordName() {
  try {
    return fs.readdirSync(runsDir()).filter((name) => RECORD_NAME.test(name)).sort().pop() ?? null
  } catch {
    return null
  }
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch {
    return null
  }
}

function incompleteCommit() {
  const file = path.join(runsDir(), COMMIT_MARKER)
  if (!fs.existsSync(file)) return null
  const marker = readJson(file)
  if (!marker || typeof marker !== 'object') return { unreadable: true, written: [], pending: [] }
  const written = marker.written ?? []
  return { runId: marker.runId ?? null, startedAt: marker.startedAt ?? null, written, pending: (marker.files ?? []).filter((name) => !written.includes(name)) }
}

/** True when the scored file does not come from the latest discovery file: scoring did not finish, or did not run. Unknown is false. */
function scoringIsBehind() {
  const discovered = readJson(JOBS_PATH)?.meta?.sourceRunId
  const scoredFrom = readJson(SCORED_PATH)?.meta?.discoveryRunId
  return Boolean(discovered && scoredFrom && discovered !== scoredFrom)
}

/** Python cleans what it writes by pattern; only this process knows the stored key values, so every string is masked here too. */
function maskStrings(value) {
  if (typeof value === 'string') return maskSecrets(value)
  if (Array.isArray(value)) return value.map(maskStrings)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, maskStrings(item)]))
  return value
}

/**
 * GET /api/rescrape/status?after=N: the latest run, its events from line N on, and whether it is alive. The files answer; Python
 * is asked only about a record that says running, so a finished run costs no process. Also reports a stale commit marker.
 */
export async function rescrapeStatus(after, options = {}) {
  const { reconcile = reconcileRuns } = options
  const cursor = /^\d+$/.test(String(after ?? '')) ? Number(after) : 0
  let name = latestRecordName()
  if (!name) return { status: 200, body: { ok: true, active: false, run: null, events: [], next: 0, incompleteCommit: incompleteCommit(), scoringBehind: false } }
  let run = readJson(path.join(runsDir(), name))
  let active = false
  if (run?.status === 'running') {
    try {
      active = (await reconcile(options)).busy
      if (!active) {
        name = latestRecordName()
        run = readJson(path.join(runsDir(), name))
      }
    } catch {
      active = true // it cannot tell, and the record says running: report what is written
    }
  }
  const { events, next } = readEventsFile(path.join(runsDir(), name.replace(/\.json$/, '.events.jsonl')), cursor)
  const answer = { ok: true, active, run, events, next, incompleteCommit: active ? null : incompleteCommit(), scoringBehind: active ? false : scoringIsBehind() }
  return { status: 200, body: maskStrings(answer) }
}
