import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { handleJobHistoryRequest, resetJobHistoryCache } from '../../scripts/job-history-read.js'
import { handleApiRoutes } from '../../scripts/api-handler.js'

const A = 'aaaaaaaaaaaaaaaa'
const B = 'bbbbbbbbbbbbbbbb'
const ledger = () => ({
  version: 1,
  updatedAt: '2026-11-02T10:00:00+00:00',
  jobs: {
    [A]: {
      firstSeen: '2026-10-01T10:00:00+00:00', lastSeen: '2026-10-20T10:00:00+00:00', closedAt: null,
      llmFacts: { _fingerprint: 'FACTS-CANARY' }, provider: 'greenhouse', roleKey: 'ROLEKEY-CANARY', seenUnder: 'SEARCH-CANARY',
      job: { jobId: A, title: 'Role A', company: 'Acme', description: 'The ad of A', jobUrl: 'https://a.example/job' },
    },
    [B]: { firstSeen: '2026-10-02', lastSeen: '2026-10-03', closedAt: '2026-10-04', job: { jobId: B, title: 'OTHER-JOB-CANARY', company: 'Beta' } },
    cccccccccccccccc: { firstSeen: '2026-10-02', lastSeen: '2026-10-03', closedAt: null },
  },
})

let root
let file
let server
let base
const write = (value) => {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, typeof value === 'string' ? value : JSON.stringify(value))
}
const get = async (id, init) => {
  const res = await fetch(`${base}/api/jobs/history/${id}`, init)
  return { status: res.status, body: await res.json() }
}

beforeEach(async () => {
  resetJobHistoryCache()
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'history-read-'))
  file = path.join(root, 'data/jobs/job_history.json')
  server = http.createServer(async (req, res) => {
    if (!(await handleJobHistoryRequest(req, res, req.url.split('?')[0], { root }))) { res.statusCode = 418; res.end('{}') }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  vi.restoreAllMocks()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

describe('GET /api/jobs/history/<jobId>', () => {
  it('returns the one snapshot with when it was last seen', async () => {
    write(ledger())
    const { status, body } = await get(A)
    expect(status).toBe(200)
    expect(body).toEqual({
      found: true,
      jobId: A,
      job: ledger().jobs[A].job,
      firstSeen: '2026-10-01T10:00:00+00:00',
      lastSeen: '2026-10-20T10:00:00+00:00',
      closedAt: null,
      absentSince: null,
      absentRuns: 0,
    })
  })

  it('never returns another job or the ledger internals', async () => {
    write(ledger())
    const text = JSON.stringify((await get(A)).body)
    for (const canary of ['OTHER-JOB-CANARY', 'FACTS-CANARY', 'ROLEKEY-CANARY', 'SEARCH-CANARY', 'updatedAt']) expect(text).not.toContain(canary)
  })

  it('an unknown id is not found', async () => {
    write(ledger())
    expect(await get('dddddddddddddddd')).toEqual({ status: 404, body: { found: false } })
  })

  it.each(['__proto__', 'constructor', 'toString', 'hasOwnProperty'])('%s is an unknown id, not an object member', async (id) => {
    write(ledger())
    expect(await get(id)).toEqual({ status: 404, body: { found: false } })
  })

  it('an entry without a snapshot is not found', async () => {
    write(ledger())
    expect((await get('cccccccccccccccc')).status).toBe(404)
  })

  it.each([
    ['a path separator', 'a%2Fb'],
    ['a traversal', '..%2F..%2Fetc%2Fpasswd'],
    ['dots', 'a..b'],
    ['a space', 'a%20b'],
    ['a NUL', 'a%00b'],
    ['broken encoding', '%E0%A4%A'],
    ['a long id', 'a'.repeat(65)],
    ['an extra segment', `${A}/more`],
  ])('refuses %s, without reading the ledger', async (_name, id) => {
    write(ledger())
    const read = vi.spyOn(fs.promises, 'readFile')
    expect((await get(id)).status).toBe(400)
    expect(read).not.toHaveBeenCalled()
  })

  it('no ledger file is not found and creates nothing', async () => {
    expect(await get(A)).toEqual({ status: 404, body: { found: false } })
    expect(fs.existsSync(path.dirname(file))).toBe(false)
  })

  it.each(['{ not json', '[]', '{"jobs": []}'])('an unreadable ledger answers 503 and is left where it is: %s', async (content) => {
    write(content)
    const { status, body } = await get(A)
    expect(status).toBe(503)
    expect(body.found).toBe(false)
    expect(fs.readFileSync(file, 'utf-8')).toBe(content)
    expect(fs.readdirSync(path.dirname(file))).toEqual(['job_history.json'])
  })

  it('refuses every method but GET', async () => {
    write(ledger())
    for (const method of ['POST', 'PUT', 'DELETE']) expect((await get(A, { method })).status).toBe(405)
  })

  it('does not touch the file', async () => {
    write(ledger())
    const before = fs.statSync(file)
    const bytes = fs.readFileSync(file, 'utf-8')
    await get(A)
    expect(fs.readFileSync(file, 'utf-8')).toBe(bytes)
    expect(fs.statSync(file).mtimeMs).toBe(before.mtimeMs)
  })

  it('parses the file once while it is unchanged, and again after a run replaces it', async () => {
    write(ledger())
    const read = vi.spyOn(fs.promises, 'readFile')
    await Promise.all([get(A), get(B)])
    await get(A)
    expect(read).toHaveBeenCalledTimes(1)

    const next = ledger()
    next.jobs[A].lastSeen = '2026-11-01T10:00:00+00:00'
    write(next)
    fs.utimesSync(file, new Date(), new Date(Date.now() + 5000))
    expect((await get(A)).body.lastSeen).toBe('2026-11-01T10:00:00+00:00')
    expect(read).toHaveBeenCalledTimes(2)
  })

  it('a failed parse is not cached: a repaired file is read', async () => {
    write('{ not json')
    expect((await get(A)).status).toBe(503)
    write(ledger())
    fs.utimesSync(file, new Date(), new Date(Date.now() + 5000))
    expect((await get(A)).status).toBe(200)
  })
})

describe('the route in the API', () => {
  const call = (method, url, headers = {}) => new Promise((resolve) => {
    const res = {
      statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v },
      end(text) { resolve({ status: this.statusCode, text }) },
    }
    handleApiRoutes({ method, url, headers }, res)
  })

  it('is wired in behind the request guard', async () => {
    // an invalid id answers before any file is read, so this test does not reach the real ledger
    expect((await call('GET', '/api/jobs/history/a%2Fb')).status).toBe(400)
    expect((await call('GET', '/api/jobs/history/a%2Fb', { host: 'holojob.void', origin: 'https://evil.example' })).status).toBe(403)
  })
})
