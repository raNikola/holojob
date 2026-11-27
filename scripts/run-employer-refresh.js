#!/usr/bin/env node
/**
 * Refresh a discovered ad's text from the employer's page (package 13). Python (`python/job_scoring/employer_refresh.py`) fetches the
 * page with the SSRF-limited fetcher, stores the text as a proposal and answers a line diff against the scraped text. No model, no
 * candidate data: only the job id (argv) and the address the owner typed (stdin) go to Python. The proposal text stays on the server;
 * accepting it is `runEmployerAccept` in run-kept-rescore.js. Failure messages are chosen here from codes, never from the page.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { failureMessage } from './run-ad-fill.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/job_scoring/employer_refresh.py')
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/

function runPython(args, input, { spawnFn = spawn, python = VENV_PYTHON } = {}) {
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
    child.stdin.end(input ?? '')
  })
}

const usable = (options) => options.spawnFn || fs.existsSync(options.python ?? VENV_PYTHON)

/** @returns {Promise<{ status: number, body: object }>} */
export async function proposeEmployerText(jobId, url, options = {}) {
  if (typeof jobId !== 'string' || !JOB_ID.test(jobId)) return { status: 422, body: { ok: false, error: 'invalid', field: 'jobId' } }
  if (typeof url !== 'string' || !url.trim() || url.length > 2048) return { status: 422, body: { ok: false, error: 'invalid', field: 'url' } }
  if (!usable(options)) return { status: 503, body: { ok: false, error: 'no_python' } }
  const { code, result } = await runPython(['propose', '--job-id=' + jobId], JSON.stringify({ url }), options)
  if (code === 0 && result.ok) return { status: 200, body: result }
  if (code === 4) return { status: 404, body: { ok: false, error: 'not_in_history' } }
  if (code === 3) return { status: 200, body: { ok: false, error: String(result.error ?? 'unreadable'), message: failureMessage(result.error, result.status) } }
  return { status: 500, body: { ok: false, error: 'fetch_failed' } }
}

/** @returns {Promise<{ status: number, body: object }>} */
export async function discardEmployerText(jobId, options = {}) {
  if (typeof jobId !== 'string' || !JOB_ID.test(jobId)) return { status: 422, body: { ok: false, error: 'invalid', field: 'jobId' } }
  if (!usable(options)) return { status: 503, body: { ok: false, error: 'no_python' } }
  const { code, result } = await runPython(['discard', '--job-id=' + jobId], '', options)
  return code === 0 && result.ok ? { status: 200, body: { ok: true } } : { status: 500, body: { ok: false, error: 'discard_failed' } }
}
