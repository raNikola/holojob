/**
 * GET /api/jobs/derived?jobId=ID: what Job Details shows beside an ad that is worked out on every read and never stored: the package 4 text
 * labels (from the effective description, so the owner's pasted or refreshed text wins) and the package 7 repost count. The rules are
 * python/job_scoring/job_derived.py; this is only the route. It writes nothing and changes no score, filter or row.
 */

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = 'python/job_scoring/job_derived.py'
const ROUTE = '/api/jobs/derived'
const TIMEOUT_MS = 30_000
const JOB_ID = /^[A-Za-z0-9_-]{1,64}$/

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(typeof body === 'string' ? body : JSON.stringify(body))
}

function run({ root, python, spawnFn, jobId }) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let child
    try {
      child = spawnFn(python, [path.join(root, SCRIPT), '--root', root, '--job-id', jobId], { cwd: root, stdio: ['ignore', 'pipe', 'ignore'], timeout: TIMEOUT_MS })
    } catch (error) {
      reject(error)
      return
    }
    child.stdout?.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
    child.on('error', reject)
    child.on('close', (code) => {
      const text = Buffer.concat(chunks).toString('utf-8')
      let answer = null
      try { answer = JSON.parse(text) } catch { /* no JSON */ }
      if (code === 0 && answer?.ok === true) resolve(text)
      else reject(new Error(answer?.message ?? `The ad details could not be worked out (exit ${code}).`))
    })
  })
}

/** @returns {Promise<boolean>} true when the request was for this route. `python` and `spawnFn` are for the tests. */
export async function handleJobDerivedRequest(req, res, url, { root = ROOT, python = path.join(root, '.venv/bin/python'), spawnFn = spawn } = {}) {
  if (url !== ROUTE) return false
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET')
    send(res, 405, { error: 'Method not allowed' })
    return true
  }
  const jobId = new URLSearchParams(String(req.url ?? '').split('?')[1] ?? '').get('jobId') ?? ''
  if (!JOB_ID.test(jobId)) {
    send(res, 400, { error: 'jobId must be an ad id' })
    return true
  }
  try {
    send(res, 200, await run({ root, python, spawnFn, jobId }))
  } catch (error) {
    send(res, 500, { error: error.message })
  }
  return true
}
