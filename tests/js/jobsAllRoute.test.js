// GET /api/jobs/all, the Node half (slice S5e2). The rows and classes are python/job_discovery/all_ads.py, tested in
// tests/python/test_all_ads.py. The tests with `real` run that script for real through the system python3 of the node image.
import { execFileSync } from 'node:child_process'
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleJobsAllRequest } from '../../scripts/job-all-read.js'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { ViewUnrecoverable } from '../../scripts/view-guard.js'

const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..')
const hasPython = (() => {
  try { execFileSync('python3', ['-V']); return true } catch { return false }
})()
let root

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'jobs-all-'))
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
  fs.mkdirSync(path.join(root, 'python'))
  fs.symlinkSync(path.join(REPO, 'python/job_discovery'), path.join(root, 'python/job_discovery'))
})
afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

function call(options, { method = 'GET', url = '/api/jobs/all' } = {}) {
  return new Promise((resolve, reject) => {
    const res = {
      statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v },
      end(text) {
        let json = null
        try { json = JSON.parse(text) } catch { /* not JSON */ }
        resolve({ status: this.statusCode, json, text, headers: this.headers })
      },
    }
    handleJobsAllRequest({ method, url }, res, url, { root, ...options }).then((done) => { if (!done) resolve({ handled: false }) }, reject)
  })
}

/** A child process that answers with `stdout` and exits with `code`. */
function fakeSpawn(stdout, code) {
  const calls = []
  const spawnFn = (python, args, options) => {
    calls.push({ python, args, options })
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(stdout)); child.emit('close', code) })
    return child
  }
  return { spawnFn, calls }
}

const current = async () => ({ regenerated: false })
const ANSWER = JSON.stringify({ ok: true, meta: { counts: {} }, rows: [{ jobId: 'a' }] })

describe('the route', () => {
  it('answers only its own address', async () => {
    const { spawnFn, calls } = fakeSpawn(ANSWER, 0)
    expect(await call({ spawnFn, ensureView: current }, { url: '/api/jobs/history/a' })).toEqual({ handled: false })
    expect(calls).toEqual([])
  })

  it('refuses every method but GET and starts nothing', async () => {
    const { spawnFn, calls } = fakeSpawn(ANSWER, 0)
    const ensureView = vi.fn(current)
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      const answer = await call({ spawnFn, ensureView }, { method })
      expect(answer.status).toBe(405)
      expect(answer.headers.Allow).toBe('GET')
    }
    expect(calls).toEqual([])
    expect(ensureView).not.toHaveBeenCalled()
  })

  it('makes the view check first, then sends the answer as it came', async () => {
    const order = []
    const { spawnFn, calls } = fakeSpawn(ANSWER, 0)
    const answer = await call({
      python: 'the-python',
      spawnFn: (...args) => { order.push('list'); return spawnFn(...args) },
      ensureView: async (options) => { order.push('check'); expect(options).toEqual({ root, python: 'the-python' }) },
    })
    expect(order).toEqual(['check', 'list'])
    expect(answer.status).toBe(200)
    expect(answer.text).toBe(ANSWER)
    expect(calls[0].python).toBe('the-python')
    expect(calls[0].args).toEqual([path.join(root, 'python/job_discovery/all_ads.py'), '--root', root])
  })

  it('a view that cannot be rebuilt is 503 view_unrecoverable, with no list and nothing started', async () => {
    const { spawnFn, calls } = fakeSpawn(ANSWER, 0)
    const answer = await call({ spawnFn, ensureView: async () => { throw new ViewUnrecoverable('the reason') } })
    expect(answer.status).toBe(503)
    expect(answer.json).toEqual({ ok: false, error: 'view_unrecoverable', message: 'the reason' })
    expect(calls).toEqual([])
  })

  it('a ledger that cannot be read is 503 with the reason Python gave and no list', async () => {
    const { spawnFn } = fakeSpawn(JSON.stringify({ ok: false, message: 'cannot be read' }), 3)
    const answer = await call({ spawnFn, ensureView: current })
    expect(answer.status).toBe(503)
    expect(answer.json).toEqual({ ok: false, error: 'view_unrecoverable', message: 'cannot be read' })
  })

  it('a failed step with no JSON, half an answer or a process that cannot start is 503 and sends nothing of it', async () => {
    for (const stdout of ['', '{"ok": true, "rows": [{"jobId"']) {
      const { spawnFn } = fakeSpawn(stdout, 1)
      const answer = await call({ spawnFn, ensureView: current })
      expect(answer.status).toBe(503)
      expect(answer.json.rows).toBeUndefined()
      expect(answer.text).not.toContain('jobId')
    }
    const started = await call({ spawnFn: () => { throw new Error('no python') }, ensureView: current })
    expect(started.status).toBe(503)
    const emitted = await call({
      spawnFn: () => { const child = new EventEmitter(); setImmediate(() => child.emit('error', new Error('ENOENT'))); return child },
      ensureView: current,
    })
    expect(emitted.status).toBe(503)
  })

  it('another failure of the check is 500, not a list', async () => {
    const answer = await call({ spawnFn: fakeSpawn(ANSWER, 0).spawnFn, ensureView: async () => { throw new Error('odd') } })
    expect(answer.status).toBe(500)
    expect(answer.json.rows).toBeUndefined()
  })
})

const job = (n) => ({ jobId: `j${n}`, title: `Ad ${n}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${n}`, description: 'THE AD TEXT', provider: 'greenhouse' })
const LEDGER = {
  generation: 4,
  version: 1,
  lastImport: { runId: 'r2', at: '2026-11-03T10:00:00+00:00', meta: { providers: ['greenhouse'] } },
  jobs: {
    j1: { firstSeen: 'x', lastSeen: 'x', provider: 'greenhouse', seenUnder: 'k', lastRunId: 'r2', job: job(1) },
    j2: { firstSeen: 'x', lastSeen: 'x', provider: 'greenhouse', seenUnder: 'k', lastRunId: 'r1', job: job(2) },
    j3: { firstSeen: 'x', lastSeen: 'x', provider: 'greenhouse', seenUnder: 'old', job: job(3) },
    j4: { firstSeen: 'x', lastSeen: 'x', provider: 'greenhouse', seenUnder: 'k', closedAt: '2026-11-01', job: job(4) },
  },
}
const FILTERED = {
  version: 1,
  appliedRuns: ['r2'],
  ads: {
    f1: { source: 'infostud', title: 'Chef', company: 'B', location: 'Niš', url: 'https://y.example/1', reason: 'title_not_matched', firstSeen: 'x', lastSeen: 'x', inLedger: false },
    f2: { source: 'infostud', title: '', company: 'B', location: 'Niš', url: 'https://y.example/2', reason: 'no_title', firstSeen: 'x', lastSeen: 'x', inLedger: false },
    j2: { source: 'greenhouse', title: 'Ad 2', company: 'Acme', location: 'Remote', url: 'https://x.example/2', reason: 'title_not_matched', firstSeen: 'x', lastSeen: 'x', inLedger: true },
  },
}
const VIEW = { meta: { ledgerGeneration: 4, generatedAt: 'x' }, jobs: [job(1)] }

function place({ ledger = JSON.stringify(LEDGER, null, 1), view = JSON.stringify(VIEW, null, 1), filtered = JSON.stringify(FILTERED) } = {}) {
  const dir = path.join(root, 'data/jobs')
  fs.writeFileSync(path.join(dir, 'job_history.json'), ledger)
  fs.writeFileSync(path.join(dir, 'discovered_jobs.json'), view)
  if (filtered !== null) fs.writeFileSync(path.join(dir, 'filtered_ads.json'), filtered)
}

function everyFile() {
  const found = {}
  for (const name of fs.readdirSync(root, { recursive: true })) {
    const file = path.join(root, String(name))
    const info = fs.lstatSync(file)
    if (info.isFile()) found[String(name)] = [fs.readFileSync(file).toString('base64'), info.mtimeMs]
  }
  return found
}

describe.skipIf(!hasPython)('the real script through the route', () => {
  const real = { python: 'python3' }

  it('gives one row an ad, with classes, counts and no description, and writes nothing', async () => {
    place()
    const before = everyFile()
    const answer = await call(real)
    expect(answer.status).toBe(200)
    expect(Object.fromEntries(answer.json.rows.map((r) => [r.jobId, r.class]))).toEqual({ j1: 'found', j2: 'absent', j3: 'older_key', j4: 'closed', f1: 'filtered' })
    expect(answer.json.meta.counts).toMatchObject({ found: 1, absent: 1, older_key: 1, closed: 1, filtered: 1, held: 0, stale: 0, filtered_incomplete: 0 })
    expect(answer.json.meta.diagnostics).toMatchObject({ filteredAlsoInLedger: 1, filteredWithoutTitleOrUrl: 1 })
    expect(answer.text).not.toContain('THE AD TEXT')
    expect(answer.text).not.toContain('"description"')
    expect(answer.json.rows.find((r) => r.jobId === 'j2').from).toBe('ledger')
    expect(everyFile()).toEqual(before)
  })

  it('an unreadable ledger with the generation still readable passes the view check and is still 503 with no list', async () => {
    place({ ledger: '{ "generation": 4, "jobs": { "cut' })
    const before = everyFile()
    const answer = await call(real)
    expect(answer.status).toBe(503)
    expect(answer.json.error).toBe('view_unrecoverable')
    expect(answer.json.rows).toBeUndefined()
    expect(answer.text).not.toContain('Chef')
    expect(everyFile()).toEqual(before)
  })

  it('no filtered file yet: the ledger rows, and it says so', async () => {
    place({ filtered: null })
    const answer = await call(real)
    expect(answer.status).toBe(200)
    expect(answer.json.meta.filteredFile).toBe('missing')
    expect(answer.json.rows).toHaveLength(4)
  })

  it('no files at all: an empty list', async () => {
    const answer = await call(real)
    expect(answer.status).toBe(200)
    expect(answer.json.rows).toEqual([])
  })
})

describe('in the API', () => {
  const api = (method, url, headers = {}) => new Promise((resolve) => {
    const res = {
      statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v },
      end(text) { resolve({ status: this.statusCode, text }) },
    }
    handleApiRoutes({ method, url, headers }, res)
  })

  it('is wired in behind the request guard', async () => {
    // both answer before any file is read, so this test does not reach the real ledger
    const refused = await api('POST', '/api/jobs/all', { 'content-type': 'application/json', host: 'careeros.void', origin: 'https://evil.example' })
    expect(refused.status).toBe(403)
    const wrong = await api('DELETE', '/api/jobs/all')
    expect(wrong.status).toBe(405)
  })
})
