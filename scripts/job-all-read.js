/**
 * GET /api/jobs/all: every ad known, as slim rows with a class and a reason (slice S5e2). The rows and the rules are
 * python/job_discovery/all_ads.py; this is only the route.
 *
 * It changes no job data. The one thing that can write is the check every job route makes first, `ensureViewCurrent`, which rebuilds
 * a view that is behind the ledger. A view that cannot be rebuilt, and a ledger that cannot be read, both answer 503
 * view_unrecoverable and send no list.
 */

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { ViewUnrecoverable, ensureViewCurrent, viewUnrecoverableAnswer } from './view-guard.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = 'python/job_discovery/all_ads.py'
const ROUTE = '/api/jobs/all'
const TIMEOUT_MS = 60_000

function send(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(typeof body === 'string' ? body : JSON.stringify(body))
}

/** The JSON text of the answer. Rejects with ViewUnrecoverable, and the reason Python gave, when there is no list to send. */
function readAll({ root, python, spawnFn }) {
  return new Promise((resolve, reject) => {
    const failed = (reason) => reject(new ViewUnrecoverable(reason))
    const chunks = []
    let child
    try {
      child = spawnFn(python, [path.join(root, SCRIPT), '--root', root], { cwd: root, stdio: ['ignore', 'pipe', 'ignore'], timeout: TIMEOUT_MS })
    } catch (error) {
      failed(`The list of all ads could not be made: ${error.message}`)
      return
    }
    child.stdout?.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
    child.on('error', (error) => failed(`The list of all ads could not be made: ${error.message}`))
    child.on('close', (code) => {
      const text = Buffer.concat(chunks).toString('utf-8')
      if (code === 0) {
        resolve(text)
        return
      }
      let answer = null
      try { answer = JSON.parse(text) } catch { /* no JSON: report the exit code */ }
      failed(answer?.message ?? `The list of all ads could not be made (exit ${code}).`)
    })
  })
}

/** @returns {Promise<boolean>} true when the request was for this route. `python`, `spawnFn` and `ensureView` are for the tests. */
export async function handleJobsAllRequest(req, res, url, { root = ROOT, python = path.join(root, '.venv/bin/python'), spawnFn = spawn, ensureView = ensureViewCurrent } = {}) {
  if (url !== ROUTE) return false
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET')
    send(res, 405, { error: 'Method not allowed' })
    return true
  }
  try {
    await ensureView({ root, python })
    send(res, 200, await readAll({ root, python, spawnFn }))
  } catch (error) {
    if (error instanceof ViewUnrecoverable) send(res, 503, viewUnrecoverableAnswer(error))
    else send(res, 500, { error: error.message })
  }
  return true
}
