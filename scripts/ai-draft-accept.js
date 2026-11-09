/**
 * Accept an AI cover-letter draft. The draft is on the server's disk (run-ai.js writes it under
 * data/resumes/<jobId>/drafts/, where no application can attach it); this re-runs the fact gate on it now
 * (`accept_cover_letter.py`) and only a pass makes it a document. The request is the job id and `confirm: true`, nothing else:
 * the text is never taken from the browser.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/resume_generator/accept_cover_letter.py')
const JOB_ID_RE = /^[A-Za-z0-9._:-]{1,200}$/

const FAILURES = {
  invalid_job: [400, 'This job id cannot be used.'],
  no_draft: [404, 'There is no saved AI cover letter for this job. Generate one first.'],
  no_profile: [409, 'The profile or intelligence on the server could not be read, so the letter could not be checked.'],
}

export async function acceptCoverLetter({ jobId, confirm }, { spawnFn = spawn, python = VENV_PYTHON, script = SCRIPT } = {}) {
  if (confirm !== true) {
    return { status: 409, body: { ok: false, error: 'confirm_required', message: 'Confirm that the checked letter becomes a document.' } }
  }
  if (typeof jobId !== 'string' || !JOB_ID_RE.test(jobId) || jobId === '.' || jobId === '..') {
    return { status: 400, body: { ok: false, error: 'invalid_job', message: FAILURES.invalid_job[1] } }
  }
  if (spawnFn === spawn && !fs.existsSync(python)) {
    return { status: 500, body: { ok: false, error: 'not_ready', message: 'Python is not set up. Run: npm run setup:jobs' } }
  }
  const answer = await new Promise((resolve) => {
    const out = []
    const child = spawnFn(python, [script, '--job-id', jobId], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    child.stdout.on('data', (d) => out.push(d))
    child.on('error', () => resolve(null))
    child.on('close', () => {
      try { resolve(JSON.parse(Buffer.concat(out).toString('utf-8').trim().split('\n').pop())) } catch { resolve(null) }
    })
  })
  if (!answer) return { status: 500, body: { ok: false, error: 'check_failed', message: 'The letter could not be checked.' } }
  if (answer.ok) return { status: 200, body: { ok: true, passed: true, file: answer.file } }
  if (answer.error === 'facts_not_verified') {
    return {
      status: 422,
      body: { ok: false, error: 'facts_not_verified', message: 'The letter states facts the profile does not, so it was not saved as a document.', issues: (answer.issues || []).slice(0, 20) },
    }
  }
  const [status, message] = FAILURES[answer.error] || [500, 'The letter could not be checked.']
  return { status, body: { ok: false, error: answer.error || 'check_failed', message } }
}
