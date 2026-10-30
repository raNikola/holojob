#!/usr/bin/env node
/**
 * Stores and scores hand-entered jobs (Add job). The Python side is `import_job_url.py --job-json -`: no fetch, no
 * model, no network; the same score_jobs() and merge as a full re-score.
 *
 * Only the scoring fields go over, on stdin (never in argv), and nothing of the request is logged or returned:
 * Python's stderr is dropped and an error carries a field name or an exception class, never text from the job.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { scoringPayload } from '../src/modules/jobs/manualJob.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const IMPORT_SCRIPT = path.join(ROOT, 'python/job_import/import_job_url.py')
const MAX_JOBS = 200

/** The argv for a run; the jobs are not in it. `store` only stores them, `score` also scores. */
export function manualJobArgs(mode) {
  return [IMPORT_SCRIPT, '--job-json', '-', ...(mode === 'store' ? ['--store-only'] : [])]
}

const REPLY = {
  2: (r) => ({ status: 422, body: { ok: false, error: 'invalid', field: typeof r.field === 'string' ? r.field : 'job' } }),
  3: (r) => ({ status: 409, body: { ok: false, error: 'duplicate', existing: r.existing ?? null } }),
  4: (r) => ({ status: 503, body: { ok: false, error: 'no_intelligence', saved: r.saved ?? [] } }),
  5: (r) => ({ status: 500, body: { ok: false, error: 'scoring_failed', detail: typeof r.detail === 'string' ? r.detail : '', saved: r.saved ?? [] } }),
}

/**
 * @param {object[]} jobs stored manual jobs; reduced to the scoring fields here
 * @param {{ mode?: 'score' | 'store', spawnFn?: typeof spawn, python?: string }} [options]
 * @returns {Promise<{ status: number, body: object }>}
 */
export function runManualJobs(jobs, { mode = 'score', spawnFn = spawn, python = VENV_PYTHON } = {}) {
  if (!Array.isArray(jobs) || !jobs.length || jobs.length > MAX_JOBS || !jobs.every((j) => j && typeof j === 'object' && typeof j.jobId === 'string')) {
    return Promise.resolve({ status: 422, body: { ok: false, error: 'invalid', field: 'job' } })
  }
  if (spawnFn === spawn && !fs.existsSync(python)) {
    return Promise.resolve({ status: 503, body: { ok: false, error: 'no_python' } })
  }
  const payload = JSON.stringify(jobs.map(scoringPayload))
  return new Promise((resolve) => {
    const out = []
    const child = spawnFn(python, manualJobArgs(mode), { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    child.stdout.on('data', (d) => out.push(d))
    child.stderr?.on('data', () => {})
    child.on('error', () => resolve({ status: 500, body: { ok: false, error: 'scoring_failed', detail: 'SpawnError' } }))
    child.on('close', (code) => {
      let result = {}
      try {
        result = JSON.parse(Buffer.concat(out).toString('utf-8').trim().split('\n').pop())
      } catch {
        // an unreadable answer is a failure below
      }
      if (code === 0 && result.ok) resolve({ status: 200, body: { ok: true, jobs: result.jobs ?? [], skipped: result.skipped ?? [], stored: result.stored ?? [] } })
      else resolve((REPLY[code] ?? REPLY[5])(result))
    })
    child.stdin.end(payload)
  })
}
