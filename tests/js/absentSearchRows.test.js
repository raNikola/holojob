// @vitest-environment jsdom
// Open ads of a search source that the latest search did not return (class "absent") stay scored and in Active within the Settings period `activeWindowDays`,
// and All keeps every one (owner decisions 2026-11-24; docs/redesign/JOBS_LIST_SERVER_PLAN.md). On the server's list the period is read on the server, from
// Settings, and each answer says which it used; the scored rows reach the screen through the list and never enter the browser's stored list.
import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { SCORED, routeRow, scoredRow, startListServer } from './setup/jobsListServer.js'
import { ago, countWrites, mountScreen, routeAnswer, settle, stubServer, viewport } from './setup/jobsScreenHarness.js'
import { routeRow as screenRouteRow } from './setup/jobsScreenHarness.js'

const DAY = 86400000
const NOW = Date.parse('2026-11-20T12:00:00Z')
const seen = (days) => new Date(NOW - days * DAY).toISOString()

// four ads the latest search returned, and five it did not (seen 2, 13, 14, 15 and 40 days ago), all scored
const FOUND = SCORED.slice(0, 4)
const GONE = [[4, 2], [5, 13], [6, 14], [7, 15], [8, 40]].map(([i, days]) => ({ ad: scoredRow(i, { matchScore: 80 }), days }))
const ROWS = [...FOUND.map((row) => routeRow(row, 'found')), ...GONE.map(({ ad, days }) => ({ ...routeRow(ad, 'absent'), lastSeen: seen(days) }))]
const SCORED_ALL = [...FOUND, ...GONE.map(({ ad }) => ad)]
const GONE_IDS = GONE.map(({ ad }) => ad.jobId)

describe('the server list and the Settings period', () => {
  let server
  beforeEach(async () => { server = await startListServer({ scored: SCORED_ALL, routeRows: ROWS, pageSize: 50, windowDays: 14 }) })
  afterEach(async () => {
    setGateRunner()
    await server.close()
  })
  const list = (body) => server.fetchFn('/api/jobs/list', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ offset: 0, ...body }) }).then(async (res) => ({ status: res.status, json: await res.json() }))
  const goneIn = (json) => json.rows.filter((row) => GONE_IDS.includes(row.jobId)).map((row) => row.jobId)

  it('Active keeps an absent ad seen within the period, the end day included, and All keeps every one', async () => {
    const active = (await list({ mode: 'active' })).json
    expect(goneIn(active)).toEqual(expect.arrayContaining([GONE_IDS[0], GONE_IDS[1], GONE_IDS[2]])) // 2, 13 and exactly 14 days
    expect(goneIn(active)).toHaveLength(3) // not the one seen 15 days ago, nor 40
    const all = (await list({ mode: 'all' })).json
    expect(goneIn(all)).toHaveLength(5) // All keeps the whole history
    expect(active.activeWindowDays).toBe(14) // the answer says which period it used
  })

  it('a row kept this way is scored and in a tier, is "not in the latest search", and is never closed', async () => {
    const active = (await list({ mode: 'active' })).json
    const row = active.rows.find((r) => r.jobId === GONE_IDS[0])
    expect(row).toMatchObject({ class: 'absent', matchScore: 80, closedAt: null })
    expect(row.isClosed).not.toBe(true)
    expect(row.serverOnly).toBeUndefined() // the server holds its scored row
  })

  it.each([[1, 0], [7, 1], [14, 3], [15, 4], [40, 5], [365, 5]])('with a period of %i days Active holds %i of them, and the counts say the same', async (days, expected) => {
    await server.close()
    server = await startListServer({ scored: SCORED_ALL, routeRows: ROWS, pageSize: 50, windowDays: days })
    const { json } = await list({ mode: 'active' })
    expect(goneIn(json)).toHaveLength(expected)
    expect(json.activeWindowDays).toBe(days)
    expect(json.total).toBe(4 + expected)
  })

  it('the period is Settings\': read through the gate, and an invalid one is an error that names the field, never a guess', async () => {
    // the helper's server gives the period by hand; this is a handler call that reads the gate, as the route does in production
    const { handleJobsListRequest, clearListIndex } = await import('../../scripts/job-list.js')
    clearListIndex()
    const call = (settings) => new Promise((resolve) => {
      setGateRunner(async () => ({ settings }))
      const res = { statusCode: 200, setHeader() {}, end(text) { resolve({ status: this.statusCode, json: JSON.parse(text) }) } }
      handleJobsListRequest({ method: 'GET', url: '/api/jobs/list?mode=active' }, res, '/api/jobs/list', { root: server.root, python: 'python3', spawnFn: server.spawnFn, ensureView: async () => {}, now: () => NOW })
    })
    const ok = await call({ jobsPageSize: 50, activeWindowDays: 21 })
    expect(ok.status).toBe(200)
    expect(ok.json.activeWindowDays).toBe(21)
    for (const bad of [undefined, null, 0, -3, 1.5, 366, '14']) {
      const refused = await call({ jobsPageSize: 50, activeWindowDays: bad })
      expect(refused.status).toBe(500)
      expect(refused.json.error).toMatch(/activeWindowDays/)
      expect(refused.json).not.toHaveProperty('rows')
    }
  })

  it('a request cannot name the period: it is a Settings field', async () => {
    expect((await list({ mode: 'active', activeWindowDays: 365 })).status).toBe(400)
    expect((await server.fetchFn('/api/jobs/list?mode=active&activeWindowDays=30').then((res) => res.status))).toBe(400)
  })

  it('saving Settings is a new revision, so a page of a list made under the old period is refused, not spliced', async () => {
    const first = (await list({ mode: 'active' })).json
    fs.mkdirSync(path.join(server.root, 'data/ai'), { recursive: true })
    fs.writeFileSync(path.join(server.root, 'data/ai/settings.json'), JSON.stringify({ activeWindowDays: 30 }))
    const after = (await list({ mode: 'active', revision: first.revision })).json
    expect(after).toMatchObject({ ok: true, changed: true })
    expect(after.revision).not.toBe(first.revision)
  })

  it('an absent ad that is scored does not change what a paid step takes: the rows carry the mark paid steps skip', async () => {
    const row = (await list({ mode: 'all' })).json.rows.find((r) => r.jobId === GONE_IDS[0])
    expect(row.class).toBe('absent') // the class is the list's; the scoring side marks the row (python/job_scoring/job_history.py, tests/python/test_open_search_rows.py)
  })
})

describe('on the screen', () => {
  let screen
  beforeEach(() => viewport(true))
  afterEach(async () => {
    await screen?.unmount()
    screen = null
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  // the screen's clock is the wall clock, so these days are clear of any boundary (the boundary itself is tested above, with a fixed clock)
  const SCREEN_DAYS = [2, 12, 13, 16, 40]
  const scoredGone = GONE.map(({ ad }, i) => ({ ...ad, title: `Gone ad ${i}`, matchScore: 80, matchLabel: 'Strong', dataStatus: 'ok' }))
  const routeGone = GONE.map((_, i) => screenRouteRow(scoredGone[i].jobId, 'absent', { title: `Gone ad ${i}`, lastSeen: ago(SCREEN_DAYS[i]), reason: 'not returned' }))

  it('the scored absent ads are in Active within the period and in All always, and none of them is written to the browser\'s list', async () => {
    const server = stubServer({ route: () => routeAnswer(routeGone), scoredRows: scoredGone, windowDays: 14 })
    screen = await mountScreen({ stored: [], server: true })
    const writes = countWrites(screen.key)
    await settle()
    for (const inside of ['Gone ad 0', 'Gone ad 1', 'Gone ad 2']) expect(screen.row(inside)).toBeTruthy()
    expect(screen.row('Gone ad 3')).toBeUndefined() // seen 16 days ago: outside the period
    expect(screen.row('Gone ad 4')).toBeUndefined()
    expect(screen.row('Gone ad 0').textContent).toContain('Not in latest search')
    await screen.click(screen.button(/^All$/))
    await settle()
    for (let i = 0; i < 5; i += 1) expect(screen.row(`Gone ad ${i}`)).toBeTruthy()
    expect(writes()).toBe(0) // setItem on the list's key was never called
    expect(screen.storedJobs?.() ?? []).toEqual([])
    expect(server.paths).not.toContain('/api/scoring/jobs')
    expect(server.listCalls.every((call) => !('activeWindowDays' in call))).toBe(true) // the browser names no period: the server reads Settings
  })

  it('by default Active keeps the ads a SEARCH did not return, and leaves out the ones a complete check of the company\'s board did not list', async () => {
    const boardProven = screenRouteRow(scoredGone[0].jobId, 'absent', { title: 'Gone ad 0', lastSeen: ago(2), absentSince: ago(2), reason: 'not on the board' })
    stubServer({ route: () => routeAnswer([boardProven, ...routeGone.slice(1)]), scoredRows: scoredGone, windowDays: 14 })
    screen = await mountScreen({ stored: [], server: true, filters: { showNotOnBoard: false } })
    await settle()
    expect(screen.row('Gone ad 0')).toBeUndefined() // a board check proved it gone: left out, as since 2026-11-18
    expect(screen.row('Gone ad 1')).toBeTruthy() // a search did not return it: it proves nothing, so it stays within the period
    expect(screen.row('Gone ad 2')).toBeTruthy()
    expect(screen.text()).toContain("1 ad is not on the company's board") // the notice counts only the board-proven ones
  })

  it('the label of the recent filter names the period the server used', async () => {
    stubServer({ route: () => routeAnswer(routeGone), scoredRows: scoredGone, windowDays: 30 })
    screen = await mountScreen({ stored: [], server: true })
    await screen.click(screen.button(/^All$/))
    await settle()
    expect(screen.box(/Seen in the last 30 days/)).toBeTruthy()
    await screen.click(screen.box(/Seen in the last 30 days/))
    await settle()
    expect(screen.row('Gone ad 4')).toBeUndefined() // 40 days: out of 30
    expect(screen.row('Gone ad 3')).toBeTruthy() // 16 days: within 30
  })
})
