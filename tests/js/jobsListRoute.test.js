// GET /api/jobs/list and /api/jobs/list/ad (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2). The rules are `queryJobList`, tested in jobListParity.test.js; here
// is what the route adds: the request checks, the page size from Settings, the revision, the index held in memory, slim rows, and the full ad.
// The route runs for real over a temp data dir. The Python step (all_ads.py) is a fake child process, as in jobsAllRoute.test.js.
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { clearListIndex, handleJobsListRequest } from '../../scripts/job-list.js'
import { ViewUnrecoverable } from '../../scripts/view-guard.js'
import { queryJobList } from '../../src/modules/jobs/jobListQuery.js'
import { importJobsFromFile } from '../../src/modules/jobs/jobStorage.js'

const NOW = Date.parse('2026-11-20T12:00:00Z')
const DAY = 86400000
const iso = (ms) => new Date(NOW - ms).toISOString()
let root

const scoredRow = (i) => ({
  jobId: `j${String(i).padStart(2, '0')}`, title: ['Senior Product Manager', 'Product Owner', 'Delivery Lead'][i % 3], company: `Co ${i % 4}`, location: i % 2 ? 'Remote' : 'Niš, Serbia',
  site: 'linkedin', provider: i % 5 === 0 ? 'greenhouse' : 'jobspy', jobUrl: `https://x.example/${i}`, description: `The long ad text number ${i}. `.repeat(20), isRemote: i % 2 === 1,
  matchScore: 30 + ((i * 17) % 60), matchLabel: 'Good', priority: ['P1', 'P2', 'P3'][i % 3], applyRecommendation: 'Maybe', blockedBy: [], dataStatus: 'ok',
  datePosted: iso((i % 9) * DAY), firstSeen: iso(20 * DAY), llmFacts: { _fingerprint: `f${i}`, big: 'x'.repeat(200) },
})
const SCORED = Array.from({ length: 12 }, (_, i) => scoredRow(i))
const routeRow = (row, cls = 'found') => ({
  jobId: row.jobId, title: row.title, company: row.company, location: row.location, jobUrl: row.jobUrl, provider: row.provider, site: row.site, isRemote: row.isRemote,
  datePosted: row.datePosted, salary: null, expiresAt: null, firstSeen: row.firstSeen, lastSeen: iso(DAY), closedAt: null, absentSince: null, class: cls, reason: cls, reasonCode: null,
  from: 'ledger', copyGroup: null, matchScore: null,
})
const ROUTE_ROWS = [...SCORED.map((row, i) => routeRow(row, i % 4 === 3 ? 'absent' : 'found')), { ...routeRow(scoredRow(90)), jobId: 'ledger-only-1', title: 'Only in the ledger' }]

function write(rel, value) {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, typeof value === 'string' ? value : JSON.stringify(value))
}
const writeScored = (rows = SCORED) => write('data/jobs/scored_jobs.json', { meta: { generatedAt: iso(0) }, jobs: rows })

beforeEach(() => {
  clearListIndex()
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'jobs-list-'))
  writeScored()
})
afterEach(() => {
  setGateRunner()
  fs.rmSync(root, { recursive: true, force: true })
})

/** A child process that answers with the route rows of the all-ads route. */
function fakeSpawn(rows = ROUTE_ROWS) {
  const calls = []
  const spawnFn = (python, args) => {
    calls.push(args)
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(JSON.stringify({ ok: true, meta: { filteredFile: 'ok', counts: {} }, rows }))); child.emit('close', 0) })
    return child
  }
  return { spawnFn, calls }
}

function call(query = '', { method = 'GET', path: urlPath = '/api/jobs/list', ...options } = {}) {
  const spawned = options.spawned ?? fakeSpawn()
  return new Promise((resolve, reject) => {
    const res = {
      statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v },
      end(text) { resolve({ status: this.statusCode, json: JSON.parse(text), headers: this.headers, spawned }) },
    }
    handleJobsListRequest({ method, url: `${urlPath}${query ? `?${query}` : ''}` }, res, urlPath, {
      root, spawnFn: spawned.spawnFn, ensureView: async () => {}, readPageSize: async () => 4, now: () => NOW, ...options,
    }).then((done) => { if (!done) resolve({ handled: false }) }, reject)
  })
}
const q = (params) => new URLSearchParams(params).toString()

/** What the query itself says for the same data: the route is only the glue around it. */
function direct(extra = {}) {
  return queryJobList({
    stored: importJobsFromFile({ meta: {}, jobs: SCORED }, null).jobs, server: ROUTE_ROWS, applications: { status: 'ready', store: { applications: {} }, settings: undefined },
    jobStateDoc: { version: 1, jobs: {} }, reference: NOW, mode: 'all', filters: {}, offset: 0, limit: 1000, ...extra,
  })
}

describe('a page', () => {
  it('is slim, in the list\'s order, and the pages together are the whole list', async () => {
    const pages = []
    let offset = 0
    for (;;) {
      const { status, json } = await call(q({ mode: 'all', offset }))
      expect(status).toBe(200)
      expect(json.limit).toBe(4) // the Settings value, not a number in the route
      pages.push(json)
      if (json.nextOffset === null) break
      expect(json.nextOffset).toBe(offset + 4)
      offset = json.nextOffset
    }
    const rows = pages.flatMap((p) => p.rows)
    expect(rows.map((r) => r.jobId)).toEqual(direct().rows.map((r) => r.jobId))
    expect(new Set(pages.map((p) => p.revision)).size).toBe(1)
    expect(pages[0].total).toBe(13)
    for (const row of rows) for (const field of ['description', 'llmFacts', 'engineShadow']) expect(row).not.toHaveProperty(field)
    expect(pages[0].counts.stats.total).toBe(12) // the stored rows, as the screen's cards count them
    expect(pages.length).toBe(4)
    expect(pages.slice(1).every((p) => p.counts === null)).toBe(true) // "Show more" pages are rows only: the first page's counts stand
    expect(pages[0].meta.filteredFile).toBe('ok')
  })

  it('a filter, a class and a picked sort reach the query', async () => {
    const filters = { searchText: 'delivery', remoteOnly: false }
    const { json } = await call(q({ mode: 'all', offset: 0, filters: JSON.stringify(filters), classes: 'absent,found', sort: JSON.stringify({ key: 'title', dir: 'asc' }) }))
    const expected = direct({ filters, classes: ['absent', 'found'], sort: { key: 'title', dir: 'asc' }, limit: 4 })
    expect(json.rows.map((r) => r.jobId)).toEqual(expected.rows.map((r) => r.jobId))
    expect(json.total).toBe(expected.total)
    expect(json.total).toBeGreaterThan(0)
  })

  it('the deadline sort reads the browser\'s day', async () => {
    const sort = JSON.stringify({ key: 'deadline', dir: 'asc' })
    expect((await call(q({ mode: 'active', sort }))).status).toBe(400)
    expect((await call(q({ mode: 'active', sort, today: String(NOW) }))).status).toBe(200)
  })

  it('ids mode answers every matching ad and the ones a bulk action can reach', async () => {
    const { json } = await call(q({ mode: 'all', ids: '1' }))
    const expected = direct({ limit: 1 })
    expect(json.ids).toEqual(expected.rows.length ? direct({ withIds: true }).ids : [])
    expect(json.ids).toHaveLength(13)
    expect(json.selectableIds).not.toContain('ledger-only-1') // a row only the ledger holds is read-only
    expect(json).not.toHaveProperty('rows')
  })

  it('an empty data dir is an empty list, not an error', async () => {
    fs.rmSync(path.join(root, 'data/jobs/scored_jobs.json'))
    const { status, json } = await call(q({ mode: 'all' }), { spawned: fakeSpawn([]) })
    expect(status).toBe(200)
    expect(json.total).toBe(0)
    expect(json.rows).toEqual([])
  })
})

describe('the revision', () => {
  it('names the data: the same while nothing moved, and a page of a list that moved is refused', async () => {
    const first = (await call(q({ mode: 'all' }))).json
    const same = await call(q({ mode: 'all', offset: 4, revision: first.revision }))
    expect(same.json.rows).toHaveLength(4)
    write('data/jobs/job-state.json', { version: 1, updatedAt: iso(0), jobs: { [`url:${SCORED[0].jobUrl}`]: { jobId: SCORED[0].jobId, status: 'saved', statusAt: iso(0), keep: false } } })
    const moved = await call(q({ mode: 'all', offset: 4, revision: first.revision }))
    expect(moved.json).toEqual({ ok: true, changed: true, revision: expect.any(String) })
    expect(moved.json.revision).not.toBe(first.revision)
    const fresh = await call(q({ mode: 'all', revision: moved.json.revision }), { readPageSize: async () => 100 })
    expect(fresh.json.rows.length).toBeGreaterThan(0)
    expect(fresh.json.rows.find((r) => r.jobId === SCORED[0].jobId).status).toBe('saved') // the new status is in the list
  })

  it('the index is kept while the revision is, and rebuilt when it changes', async () => {
    const spawned = fakeSpawn()
    await call(q({ mode: 'all' }), { spawned })
    await call(q({ mode: 'active', offset: 4 }), { spawned })
    expect(spawned.calls).toHaveLength(1)
    writeScored(SCORED.slice(0, 9))
    const after = await call(q({ mode: 'all' }), { spawned })
    expect(spawned.calls).toHaveLength(2)
    expect(after.json.counts.stats.total).toBe(9)
  })

  it('two requests at once build the index once', async () => {
    const spawned = fakeSpawn()
    await Promise.all([call(q({ mode: 'all' }), { spawned }), call(q({ mode: 'all', offset: 4 }), { spawned })])
    expect(spawned.calls).toHaveLength(1)
  })
})

describe('what the request may say', () => {
  it.each([
    ['no mode', ''],
    ['an unknown mode', 'mode=every'],
    ['a limit (the page size is Settings\')', 'mode=all&limit=500'],
    ['a negative offset', 'mode=all&offset=-1'],
    ['a fractional offset', 'mode=all&offset=1.5'],
    ['filters that are not JSON', 'mode=all&filters=%7Bnope'],
    ['an unknown filter', `mode=all&filters=${encodeURIComponent('{"drop":true}')}`],
    ['a filter of the wrong type', `mode=all&filters=${encodeURIComponent('{"searchText":5}')}`],
    ['a list filter with a number in it', `mode=all&filters=${encodeURIComponent('{"provider":[1]}')}`],
    ['an unknown sort column', `mode=all&sort=${encodeURIComponent('{"key":"password","dir":"asc"}')}`],
    ['a sort direction that is not asc or desc', `mode=all&sort=${encodeURIComponent('{"key":"title","dir":"sideways"}')}`],
    ['a today that is not a number', 'mode=all&today=yesterday'],
  ])('refuses %s with 400, before any file is read', async (_name, query) => {
    const spawned = fakeSpawn()
    const { status, json } = await call(query, { spawned })
    expect(status).toBe(400)
    expect(json.ok).toBe(false)
    expect(spawned.calls).toHaveLength(0)
  })

  it('takes every filter the Jobs screen has', async () => {
    const filters = {
      searchText: 'a', location: 'b', site: ['x'], provider: ['y'], company: ['z'], remoteOnly: true, hideNeedsVisa: true, hideNoLongerListed: true, showNotOnBoard: true,
      showOffList: false, status: 'saved', matchLabel: 'Good', roleClass: 'target', priority: ['P1'], minScore: 55, salaryMode: 'set', salaryFrom: '1000', salaryTo: 2000, salaryIncludeUnknown: false,
    }
    expect((await call(q({ mode: 'active', filters: JSON.stringify(filters) }))).status).toBe(200)
  })

  it('answers 405 to anything but GET, and leaves other URLs alone', async () => {
    expect((await call(q({ mode: 'all' }), { method: 'POST' })).status).toBe(405)
    expect((await call('', { path: '/api/jobs/all' })).handled).toBe(false)
  })

  it('is not served in demo mode', async () => {
    expect((await call(q({ mode: 'all' }), { demoMode: () => true })).status).toBe(404)
  })
})

describe('the page size', () => {
  // The route reads it from Settings through the gate, as the Settings screen saves it; here the gate answers with a settings object.
  const gateSays = (jobsPageSize) => setGateRunner(async () => ({ settings: { jobsPageSize } }))

  it.each([[null], [0], [-3], [2.5], ['10'], [undefined]])('a Settings value of %s is an error that names the field, never a guess', async (size) => {
    gateSays(size)
    const { status, json } = await call(q({ mode: 'all' }), { readPageSize: undefined })
    expect(status).toBe(500)
    expect(json.error).toMatch(/jobsPageSize/)
    expect(json).not.toHaveProperty('rows')
  })

  it('follows Settings: a new value is the next page\'s size, and the page says which it used', async () => {
    gateSays(2)
    const small = (await call(q({ mode: 'all' }), { readPageSize: undefined })).json
    gateSays(7)
    const large = (await call(q({ mode: 'all' }), { readPageSize: undefined })).json
    expect([small.rows.length, small.limit]).toEqual([2, 2])
    expect([large.rows.length, large.limit]).toEqual([7, 7])
  })

  it('ids mode needs no page size', async () => {
    gateSays(null)
    expect((await call(q({ mode: 'all', ids: '1' }), { readPageSize: undefined })).status).toBe(200)
  })
})

describe('failures say so', () => {
  it('a list that cannot be made is a 503 with the reason, and no rows', async () => {
    const { status, json } = await call(q({ mode: 'all' }), { ensureView: async () => { throw new ViewUnrecoverable('the ledger cannot be read') } })
    expect(status).toBe(503)
    expect(json).not.toHaveProperty('rows')
  })

  it('an unreadable scored file is a 500, not an empty list', async () => {
    write('data/jobs/scored_jobs.json', '{ not json')
    const { status, json } = await call(q({ mode: 'all' }))
    expect(status).toBe(500)
    expect(json.error).toMatch(/scored_jobs\.json/)
  })
})

describe('the full ad on open', () => {
  it('is the whole row, with the owner\'s status laid over it', async () => {
    write('data/jobs/job-state.json', { version: 1, updatedAt: iso(0), jobs: { [`url:${SCORED[2].jobUrl}`]: { jobId: SCORED[2].jobId, status: 'rejected', statusAt: iso(0), keep: true } } })
    const { status, json } = await call(q({ jobId: SCORED[2].jobId }), { path: '/api/jobs/list/ad' })
    expect(status).toBe(200)
    expect(json.row.description).toBe(SCORED[2].description)
    expect(json.row.llmFacts).toEqual(SCORED[2].llmFacts)
    expect(json.row.status).toBe('rejected')
    expect(json.row.keptByUser).toBe(true)
  })

  it('an ad with no scored row says where its text is, and a bad id is refused', async () => {
    const missing = await call(q({ jobId: 'ledger-only-1' }), { path: '/api/jobs/list/ad' })
    expect(missing.status).toBe(404)
    expect(missing.json.error).toMatch(/history/)
    expect((await call(q({ jobId: '../etc/passwd' }), { path: '/api/jobs/list/ad' })).status).toBe(400)
    expect((await call('', { path: '/api/jobs/list/ad' })).status).toBe(400)
  })
})
