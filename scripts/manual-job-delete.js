#!/usr/bin/env node
/**
 * Deletes one hand-entered job from the server (Delete job on Job Details).
 *
 * Order matters and is the whole safety story:
 *   1. The application store is read at delete time. ANY application record that names the job (Applied, Interview, closed, voided
 *      or not) refuses the delete with 409 `has_application`; voiding never unlocks it. An unreadable store refuses too (fails closed).
 *   2. Python (`import_job_url.py --delete-job`, under the pipeline lock) removes the row from manual_jobs.json and scored_jobs.json.
 *      A discovered (non-manual) job is refused there (422 `not_manual`).
 *   3. The job's entry in job-state.json is removed (the only place a job-state entry is ever deleted).
 * Application records, other jobs, the ledger and the discovery files are never touched.
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadStore, normalizeUrl } from './application-store.js'
import { removeJobStateEntries } from './job-state-store.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const IMPORT_SCRIPT = path.join(ROOT, 'python/job_import/import_job_url.py')
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/

/** Application ids (never contents) that name this job by id, posting key, migration id or address. */
export function applicationsForJob(store, jobId, urls = []) {
  const wanted = new Set(urls.map((u) => normalizeUrl(u)).filter(Boolean))
  return Object.values(store.applications ?? {})
    .filter((app) => {
      const posting = app.posting ?? {}
      return posting.jobId === jobId || posting.postingKey === `job:${jobId}` || app.id === `mig-${jobId}`
        || (wanted.size > 0 && wanted.has(normalizeUrl(posting.url)))
    })
    .map((app) => app.id)
}

function serverJobUrl(root, jobId) {
  try {
    const doc = JSON.parse(fs.readFileSync(path.join(root, 'data/jobs/manual_jobs.json'), 'utf-8'))
    return (doc.jobs ?? []).find((j) => j?.jobId === jobId)?.jobUrl ?? null
  } catch {
    return null
  }
}

function runDelete(jobId, { spawnFn = spawn, python = VENV_PYTHON, root = ROOT } = {}) {
  return new Promise((resolve) => {
    const out = []
    const child = spawnFn(python, [IMPORT_SCRIPT, '--delete-job', jobId, '--manual', path.join(root, 'data/jobs/manual_jobs.json'), '--scored', path.join(root, 'data/jobs/scored_jobs.json')], { cwd: root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
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

/**
 * @param {string} root
 * @param {{ jobId?: string, jobUrl?: string }} body the id, and the address the browser holds (matched against applications only)
 * @param {{ spawnFn?: Function, python?: string }} [options]
 * @returns {Promise<{ status: number, body: object }>}
 */
export async function deleteManualJob(root, body, options = {}) {
  const jobId = body?.jobId
  if (typeof jobId !== 'string' || !JOB_ID.test(jobId)) return { status: 422, body: { ok: false, error: 'invalid', field: 'jobId' } }
  let applicationIds
  try {
    const urls = [body.jobUrl, serverJobUrl(root, jobId)].filter((u) => typeof u === 'string' && u)
    applicationIds = applicationsForJob(loadStore(root), jobId, urls)
  } catch {
    return { status: 500, body: { ok: false, error: 'tracker_unreadable', message: 'The application tracker could not be read, so nothing was deleted.' } }
  }
  if (applicationIds.length) {
    return {
      status: 409,
      body: {
        ok: false,
        error: 'has_application',
        applicationIds,
        message: 'This job has an application in the tracker (including voided ones), so it cannot be deleted. Voiding the application does not unlock deletion.',
      },
    }
  }
  const pythonPath = options.python ?? VENV_PYTHON
  if (!options.spawnFn && !fs.existsSync(pythonPath)) return { status: 503, body: { ok: false, error: 'no_python' } }
  const { code, result } = await runDelete(jobId, { ...options, root })
  if (code === 75) return { status: 409, body: { ok: false, error: 'run_active', message: 'A run is active. Try again when it has finished.' } }
  if (code === 6) return { status: 422, body: { ok: false, error: 'not_manual', message: 'Only hand-entered jobs can be deleted.' } }
  if (code !== 0 || !result.ok) return { status: 500, body: { ok: false, error: 'delete_failed' } }
  const state = await removeJobStateEntries(root, jobId)
  return { status: 200, body: { ok: true, removed: { ...result.removed, state: state.removed } } }
}
