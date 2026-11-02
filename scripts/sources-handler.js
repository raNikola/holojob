/**
 * Settings > Sources routes. The rules live in python/job_discovery/source_settings.py (validation, the consent
 * check, the server's consent time, the atomic write to data/config/sources.json); this file only carries JSON to it.
 *
 *   GET  /api/sources                                              -> every source, opt-in switches and consent history
 *   PUT  /api/sources                 { boards: { joberty: { active, consentAccepted? } } }
 *   POST /api/sources/migrate-legacy  { value }                    -> the old Jobs-screen checkbox, moved once
 *
 * Answers: 200 saved, 400 invalid, 409 an opt-in source is being switched on without "consentAccepted": true
 * (the body lists which), 500 the settings could not be run. Discovery reads the same file and is the gate: a
 * source that is off here never runs, whatever a request asks for.
 */

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { maskErrorField } from './secret-mask.js'
import { readJsonObject } from './read-body.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const CLI = path.join(ROOT, 'python/job_discovery/source_settings.py')
const MAX_BODY = 16 * 1024

function runSourcesCli(command, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_PYTHON, [CLI, command], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    const out = []
    const err = []
    child.stdout.on('data', (d) => out.push(d))
    child.stderr.on('data', (d) => err.push(d))
    child.on('error', reject)
    child.on('close', (code) => {
      try {
        resolve(JSON.parse(Buffer.concat(out).toString('utf-8').trim().split('\n').pop()))
      } catch {
        reject(new Error(`Source settings exited ${code}: ${Buffer.concat(err).toString('utf-8').slice(0, 300)}`))
      }
    })
    child.stdin.end(input ? JSON.stringify(input) : '')
  })
}

let runner = runSourcesCli

/** Tests replace the CLI runner; pass nothing to restore it. */
export function setSourcesRunner(fn) {
  runner = fn || runSourcesCli
}

function send(res, status, data) {
  if (res.writableEnded) return // read-body.js has already answered 413
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(maskErrorField(data)))
}

const ROUTES = { '/api/sources': ['GET', 'PUT'], '/api/sources/migrate-legacy': ['POST'] }

/** Returns true when it answered the request. */
export async function handleSourcesRequest(req, res) {
  const url = req.url?.split('?')[0] ?? ''
  const allowed = ROUTES[url]
  if (!allowed) return false
  if (!allowed.includes(req.method)) {
    res.setHeader('Allow', allowed.join(', '))
    send(res, 405, { error: `Use ${allowed.join(' or ')}` })
    return true
  }
  try {
    if (req.method === 'GET') {
      send(res, 200, await runner('get', null))
      return true
    }
    let body
    try {
      body = await readJsonObject(req, res, { limit: MAX_BODY })
    } catch (e) {
      send(res, 400, { error: e.message })
      return true
    }
    // Only the switch and the consent flag are passed on; a consent time always comes from the server.
    const result = url === '/api/sources'
      ? await runner('put', { boards: body.boards })
      : await runner('migrate-legacy', { value: body.value })
    send(res, result?.ok ? 200 : result?.needsConsent ? 409 : 400, result)
  } catch (e) {
    send(res, 500, { error: e.message })
  }
  return true
}
