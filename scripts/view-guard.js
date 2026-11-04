/**
 * The ledger is the truth and discovered_jobs.json is a view derived from it (slice S4a). This is the Node side of
 * python/job_scoring/view_guard.py: before a route reads or serves the view, or a backup copies it, check that the view matches
 * the ledger and, if it does not, ask Python to rebuild it. If that fails the route answers with the reason and serves nothing.
 *
 * The check reads the first bytes of two files (the ledger is 18 MB): `generation` is the first key of the ledger and
 * `meta.ledgerGeneration` the first key of the view's meta. tests/fixtures/view-generation.json holds the cases both languages run.
 *
 * Node cannot take the view lock, so the rebuild is `view_guard.py ensure` in a child process. That process takes only the
 * view lock, never the pipeline lock, so it works while a run or a backup export holds the pipeline lock (see view_guard.py).
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/job_scoring/view_guard.py')
const PEEK_BYTES = 4096

export const LEDGER_GENERATION = /^\s*\{\s*"generation"\s*:\s*(\d+)\s*[,}]/
export const VIEW_GENERATION = /^\s*\{\s*"meta"\s*:\s*\{\s*"ledgerGeneration"\s*:\s*(\d+)\s*[,}]/

export class ViewUnrecoverable extends Error {
  constructor(message) {
    super(message)
    this.name = 'ViewUnrecoverable'
    this.code = 'view_unrecoverable'
  }
}

function peek(file, pattern) {
  let fd
  try {
    fd = fs.openSync(file, 'r')
    const buffer = Buffer.alloc(PEEK_BYTES)
    const read = fs.readSync(fd, buffer, 0, PEEK_BYTES, 0)
    const found = pattern.exec(buffer.subarray(0, read).toString('utf-8'))
    return found ? Number(found[1]) : null
  } catch {
    return null
  } finally {
    if (fd !== undefined) fs.closeSync(fd)
  }
}

/** Is the view the ledger's? The same rules as view_guard.state. */
export function viewState({ jobsFile, ledgerFile }) {
  const ledgerExists = fs.existsSync(ledgerFile)
  const viewExists = fs.existsSync(jobsFile)
  const ledgerGeneration = ledgerExists ? peek(ledgerFile, LEDGER_GENERATION) : null
  const viewGeneration = viewExists ? peek(jobsFile, VIEW_GENERATION) : null
  let consistent
  if (!ledgerExists) consistent = true
  else if (ledgerGeneration === null) consistent = viewGeneration === null
  else if (!viewExists) consistent = false
  else consistent = viewGeneration === ledgerGeneration
  return { consistent, ledgerGeneration, viewGeneration }
}

export function viewPaths(root = ROOT) {
  const dir = path.join(root, 'data/jobs')
  return { jobsFile: path.join(dir, 'discovered_jobs.json'), ledgerFile: path.join(dir, 'job_history.json') }
}

/**
 * Resolves {regenerated} when the view matches the ledger (rebuilding it first if it did not); rejects with ViewUnrecoverable,
 * carrying Python's reason, when it cannot be rebuilt. `spawnFn` and `python` are for the tests.
 */
export function ensureViewCurrent({ root = ROOT, python = VENV_PYTHON, script = SCRIPT, spawnFn = spawn } = {}) {
  const paths = viewPaths(root)
  if (viewState(paths).consistent) return Promise.resolve({ regenerated: false })
  return new Promise((resolve, reject) => {
    let out = ''
    let child
    try {
      child = spawnFn(python, [script, 'ensure', '--jobs', paths.jobsFile], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] })
    } catch (error) {
      reject(new ViewUnrecoverable(`The job list is out of date and the rebuild could not start: ${error.message}`))
      return
    }
    child.stdout?.on('data', (chunk) => { out += chunk.toString() })
    child.on('error', (error) => reject(new ViewUnrecoverable(`The job list is out of date and the rebuild could not start: ${error.message}`)))
    child.on('close', (code) => {
      let answer = null
      try { answer = JSON.parse(out.trim().split('\n').pop()) } catch { /* no JSON: report the exit code */ }
      if (code === 0 && answer?.ok) resolve({ regenerated: Boolean(answer.regenerated) })
      else reject(new ViewUnrecoverable(answer?.message ?? `The job list is out of date and the rebuild failed (exit ${code}).`))
    })
  })
}

/** The answer a route sends when the view cannot be rebuilt. */
export function viewUnrecoverableAnswer(error) {
  return { ok: false, error: 'view_unrecoverable', message: error.message }
}
