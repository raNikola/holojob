#!/usr/bin/env node
/**
 * Manual Re-score of one kept ad, and the pruning of the set that remembers them (Wave 2 e).
 * The Python side is python/job_scoring/rescore_kept.py: local scoring, no model, no network, so the AI budget gate
 * has nothing to approve here. A judged run (the existing confirm dialog) includes these ads like any other.
 * Only a job id travels (argv); the ad text is read from the job history ledger on the server.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadStore } from './application-store.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/job_scoring/rescore_kept.py')
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/
const MAX_IDS = 20000

const REPLY = {
  2: () => ({ status: 422, body: { ok: false, error: 'invalid', field: 'jobId' } }),
  4: (r) => ({ status: 404, body: { ok: false, error: r.error === 'no_intelligence' ? 'no_intelligence' : 'not_in_history' } }),
  75: () => ({ status: 409, body: { ok: false, error: 'run_active' } }),
}

function runPython(args, { spawnFn = spawn, python = VENV_PYTHON } = {}) {
  return new Promise((resolve) => {
    const out = []
    const child = spawnFn(python, [SCRIPT, ...args], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    child.stdout.on('data', (d) => out.push(d))
    child.stderr?.on('data', () => {})
    child.on('error', () => resolve({ code: -1, result: {} }))
    child.on('close', (code) => {
      let result = {}
      try {
        result = JSON.parse(Buffer.concat(out).toString('utf-8').trim().split('\n').pop())
      } catch {
        // an unreadable answer is a failure below
      }
      resolve({ code, result })
    })
  })
}

/** @returns {Promise<{ status: number, body: object }>} */
export async function runKeptRescore(jobId, options = {}) {
  if (typeof jobId !== 'string' || !JOB_ID.test(jobId)) return { status: 422, body: { ok: false, error: 'invalid', field: 'jobId' } }
  if (!options.spawnFn && !fs.existsSync(options.python ?? VENV_PYTHON)) return { status: 503, body: { ok: false, error: 'no_python' } }
  const { code, result } = await runPython(['--job-id=' + jobId], options)
  if (code === 0 && result.ok) return { status: 200, body: { ok: true, job: result.job } }
  return (REPLY[code] ?? (() => ({ status: 500, body: { ok: false, error: 'scoring_failed' } })))(result)
}

/** The ids of every ad that has an application. Read from the application store; never written. */
export function applicationJobIds(root = ROOT) {
  const ids = new Set()
  for (const app of Object.values(loadStore(root).applications ?? {})) {
    const id = app?.posting?.jobId
    if (typeof id === 'string') ids.add(id)
  }
  return ids
}

/**
 * Forgets every re-scored id that is no longer kept and has no application. `keptIds` is what the browser holds as kept.
 * Only the ids file changes: no stored job, score or application is touched.
 */
export async function pruneKeptRescored(keptIds, options = {}) {
  if (!Array.isArray(keptIds) || keptIds.length > MAX_IDS || !keptIds.every((i) => typeof i === 'string' && JOB_ID.test(i))) {
    return { status: 422, body: { ok: false, error: 'invalid', field: 'keptIds' } }
  }
  let withApplication
  try {
    withApplication = applicationJobIds(options.root ?? ROOT)
  } catch {
    // An unreadable application store means nobody can say which ads have one: prune nothing.
    return { status: 200, body: { ok: true, dropped: [], skipped: 'applications_unreadable' } }
  }
  const keep = [...new Set([...keptIds, ...withApplication])]
  const { code, result } = await runPython([`--prune=${keep.join(',')}`], options)
  if (code === 0 && result.ok) return { status: 200, body: { ok: true, dropped: result.dropped ?? [] } }
  return { status: 500, body: { ok: false, error: 'prune_failed' } }
}
