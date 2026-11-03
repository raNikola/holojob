#!/usr/bin/env tsx
/**
 * Proof, in the real container, that the Node side recovers a stale job list (slice S4a follow-up). It touches NO live data.
 *
 *   podman exec career-os node_modules/.bin/tsx scripts/check-view-recovery.js
 *
 * The server has no setting that points it at another data folder (every module derives ROOT from its own location), and adding
 * one would put a switch into production code. So this script builds a throwaway root in the temp folder that holds a COPY of
 * the code (scripts/, python/, package.json; src/ and node_modules are linked, read-only use) and a COPY of data/jobs/job_history.json and discovered_jobs.json, then
 * runs the real request handler (`handleApiRoutes`) from that copy on a local port. The handler, the view guard and the Python
 * rebuild are the production files; only where they look for data differs. The live files are only read, and their hashes are
 * printed before and after.
 *
 * Steps on the copy:
 *   a) the ledger generation is raised so the view is behind it; GET /api/discovery/jobs must answer 200 with a regenerated view;
 *   b) the generations of the two files then match, and the answer carries that generation;
 *   c) the ledger is made unreadable with the view still behind; the route must answer 503 view_unrecoverable and send no job list.
 * The request guard (scripts/request-guard.js) stays on: the requests carry the Host the container's CAREER_OS_ALLOWED_ORIGINS allows,
 * exactly as the reverse proxy does. A 403 from the guard is reported as an ENVIRONMENT failure (the check could not reach the
 * recovery), never as a recovery failure.
 * Exit 0 when all of it holds, 1 when the recovery failed, 2 when the environment stopped the check.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SOURCE_ROOT = path.resolve(HERE, '..')
const LEDGER = 'job_history.json'
const VIEW = 'discovered_jobs.json'
const GENERATION_PATTERN = /^\s*\{\s*"generation"\s*:\s*(\d+)/
const VIEW_PATTERN = /^\s*\{\s*"meta"\s*:\s*\{\s*"ledgerGeneration"\s*:\s*(\d+)/

class EnvironmentStop extends Error {}

function sha(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

function peek(file, pattern) {
  const fd = fs.openSync(file, 'r')
  try {
    const buffer = Buffer.alloc(4096)
    const read = fs.readSync(fd, buffer, 0, 4096, 0)
    const found = pattern.exec(buffer.subarray(0, read).toString('utf-8'))
    return found ? Number(found[1]) : null
  } finally {
    fs.closeSync(fd)
  }
}

function copyRoot({ sourceRoot, tempRoot, python }) {
  for (const entry of ['scripts', 'python']) {
    fs.cpSync(path.join(sourceRoot, entry), path.join(tempRoot, entry), {
      recursive: true,
      dereference: true, // a linked source folder must still become a real copy, or the handler would find the real data
      filter: (src) => !src.includes('__pycache__') && !src.includes(`${path.sep}tests${path.sep}`),
    })
  }
  fs.symlinkSync(path.join(sourceRoot, 'src'), path.join(tempRoot, 'src')) // shared modules the scripts import; nothing writes there
  fs.copyFileSync(path.join(sourceRoot, 'package.json'), path.join(tempRoot, 'package.json'))
  fs.symlinkSync(path.join(sourceRoot, 'node_modules'), path.join(tempRoot, 'node_modules'))
  // the view guard runs ROOT/.venv/bin/python; point it at the same interpreter the real one uses
  fs.mkdirSync(path.join(tempRoot, '.venv/bin'), { recursive: true })
  fs.symlinkSync(python, path.join(tempRoot, '.venv/bin/python'))
}

/** The Host the production guard accepts: the first of CAREER_OS_ALLOWED_ORIGINS (the container's .env), else the plain local address. */
export function allowedHost(env = process.env) {
  const first = String(env.CAREER_OS_ALLOWED_ORIGINS ?? '').split(',')[0].trim().replace(/^[a-z]+:\/\//i, '').replace(/\/.*$/, '')
  return first || null
}

function get(port, route, host) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: '127.0.0.1', port, path: route, headers: host ? { Host: host } : {} }, (res) => {
        let body = ''
        res.on('data', (chunk) => { body += chunk })
        res.on('end', () => {
          let json = null
          try { json = JSON.parse(body) } catch { /* not JSON */ }
          resolve({ status: res.statusCode, json, bytes: body.length })
        })
      })
      .on('error', reject)
  })
}

/** Returns {ok, steps[], liveUnchanged}. `log` receives each line. Exported for the test. */
export async function runCheck({ sourceRoot = SOURCE_ROOT, python, log = console.log, keep = false, host = allowedHost() } = {}) {
  const steps = []
  let environmentFailure = false
  const step = (name, ok, detail) => {
    steps.push({ name, ok, detail })
    log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
    return ok
  }
  python ??= path.join(sourceRoot, '.venv/bin/python')
  const liveDir = path.join(sourceRoot, 'data/jobs')
  const liveFiles = [LEDGER, VIEW].map((name) => path.join(liveDir, name)).filter((file) => fs.existsSync(file))
  if (liveFiles.length < 2) {
    log(`Nothing to copy: ${LEDGER} and ${VIEW} must both exist in ${liveDir}.`)
    return { ok: false, steps, liveUnchanged: true }
  }
  const liveBefore = Object.fromEntries(liveFiles.map((file) => [file, sha(file)]))
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-view-recovery-'))
  let server
  try {
    log(`Working root (a copy, deleted at the end): ${tempRoot}`)
    copyRoot({ sourceRoot, tempRoot, python })
    const jobsDir = path.join(tempRoot, 'data/jobs')
    fs.mkdirSync(jobsDir, { recursive: true })
    for (const name of [LEDGER, VIEW]) fs.copyFileSync(path.join(liveDir, name), path.join(jobsDir, name))
    const ledgerCopy = path.join(jobsDir, LEDGER)
    const viewCopy = path.join(jobsDir, VIEW)

    const startLedger = peek(ledgerCopy, GENERATION_PATTERN)
    const startView = peek(viewCopy, VIEW_PATTERN)
    log(`Copy as it is: ledger generation ${startLedger ?? 'none'}, view generation ${startView ?? 'none'}`)

    // The real handler, loaded from the copy: its ROOT is the copy.
    process.chdir(tempRoot)
    const handler = await import(pathToFileURL(path.join(tempRoot, 'scripts/api-handler.js')).href)
    server = http.createServer((req, res) => { handler.handleApiRoutes(req, res).then((done) => { if (!done) { res.statusCode = 404; res.end('{}') } }) })
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address()

    // a) make the view differ from the ledger: the ledger moves ahead by 7 generations, the view stays
    const target = (startLedger ?? startView ?? 0) + 7
    const ledger = JSON.parse(fs.readFileSync(ledgerCopy, 'utf-8'))
    delete ledger.generation
    fs.writeFileSync(ledgerCopy, JSON.stringify({ generation: target, ...ledger }, null, 1))
    const viewBytes = sha(viewCopy)
    step('setup: the copy is stale (view generation differs from the ledger)', peek(viewCopy, VIEW_PATTERN) !== peek(ledgerCopy, GENERATION_PATTERN),
      `ledger ${peek(ledgerCopy, GENERATION_PATTERN)}, view ${peek(viewCopy, VIEW_PATTERN) ?? 'none'}`)

    log(`Requests are sent with Host: ${host ?? '(none configured: the guard takes the local address)'}`)
    const first = await get(port, '/api/discovery/jobs', host)
    if (first.status === 403) {
      environmentFailure = true
      step('ENVIRONMENT: the request guard refused the check\'s own request (HTTP 403); the view recovery was not reached',
        false, `${first.json?.error ?? 'no message'}; Host sent: ${host ?? 'none'}. Check CAREER_OS_ALLOWED_ORIGINS`)
      throw new EnvironmentStop()
    }
    step('(a) the route answers 200 and the view was regenerated automatically', first.status === 200 && sha(viewCopy) !== viewBytes,
      `HTTP ${first.status}`)
    const afterLedger = peek(ledgerCopy, GENERATION_PATTERN)
    const afterView = peek(viewCopy, VIEW_PATTERN)
    step('(b) the generations match afterwards', afterLedger === target && afterView === target && first.json?.meta?.ledgerGeneration === target,
      `ledger ${afterLedger}, view ${afterView}, answer ${first.json?.meta?.ledgerGeneration}`)

    // c) ledger unreadable, view behind: the generation can still be read from the head, the rest is cut
    fs.writeFileSync(ledgerCopy, `{ "generation": ${target + 1}, "jobs": { "broken`)
    const before503 = sha(viewCopy)
    const second = await get(port, '/api/discovery/jobs', host)
    if (second.status === 403) {
      environmentFailure = true
      step('ENVIRONMENT: the request guard refused the 503 check (HTTP 403); not a recovery result', false, second.json?.error)
      throw new EnvironmentStop()
    }
    step('(c) unreadable ledger: 503 view_unrecoverable', second.status === 503 && second.json?.error === 'view_unrecoverable',
      `HTTP ${second.status}, ${second.json?.error ?? 'no error field'}`)
    step('(c) no stale job list was served', second.json?.jobs === undefined && second.json?.meta === undefined && second.bytes < 2000,
      `${second.bytes} bytes in the answer`)
    step('(c) the stale view file was left as it was (not truncated or replaced)', sha(viewCopy) === before503)
    const status = await get(port, '/api/discovery/status', host)
    step('(c) /api/discovery/status refuses too', status.status === 503 && status.json?.error === 'view_unrecoverable', `HTTP ${status.status}`)
    if (second.json?.message) log(`      reason given: ${second.json.message}`)
  } catch (error) {
    if (error instanceof EnvironmentStop) { /* already reported */ } else step('the check itself ran', false, `${error.name}: ${error.message}`)
  } finally {
    server?.close()
    process.chdir(sourceRoot)
    if (!keep) fs.rmSync(tempRoot, { recursive: true, force: true })
  }
  const liveUnchanged = Object.entries(liveBefore).every(([file, hash]) => fs.existsSync(file) && sha(file) === hash)
  step('live data/jobs/job_history.json and discovered_jobs.json unchanged (sha256 before = after)', liveUnchanged)
  const ok = steps.every((s) => s.ok)
  log(ok ? 'RESULT: ALL PASS' : environmentFailure ? 'RESULT: ENVIRONMENT FAILURE (not a recovery failure)' : 'RESULT: FAILED')
  return { ok, steps, liveUnchanged, environmentFailure }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await runCheck({ keep: process.argv.includes('--keep'), python: process.env.CHECK_VIEW_PYTHON || undefined })
  process.exit(result.ok ? 0 : result.environmentFailure ? 2 : 1)
}
