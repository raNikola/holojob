// POST /api/jobs/list with the browser's own rows (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b; a bridge removed in P5), against a real HTTP server.
// What the route adds to P2: the rows are ranked and counted with the server's for one request and stored nowhere; a field outside the allowlist is refused
// by name and never echoed; a body over the limit is a 413 in words, never a shorter list.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SCORED, startListServer, treeOf } from './setup/jobsListServer.js'
import { selectExtraRows } from '../../src/modules/jobs/extraRows.js'

let server
beforeEach(async () => { server = await startListServer({ pageSize: 50 }) })
afterEach(() => server.close())

const SECRET = 'PRIVATE-VALUE-4417'
const post = (body, { raw } = {}) => server.fetchFn('/api/jobs/list', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw ?? JSON.stringify(body) }).then(async (res) => ({ status: res.status, text: await res.clone().text(), json: await res.json().catch(() => null) }))
const get = (query) => server.fetchFn(`/api/jobs/list?${query}`).then(async (res) => ({ status: res.status, json: await res.json() }))

const browserRows = [
  { jobId: 'off1', title: 'Gone Ad', company: 'Acme', location: 'Remote', jobUrl: 'https://x.example/off1', offList: true, status: 'saved', matchScore: 80, matchLabel: 'Good', priority: 'P1', applyRecommendation: 'Apply', isRemote: true },
  { jobId: 'man1', title: 'My own job', company: 'Me', jobUrl: 'https://y.example/man1', manualEntry: true, provider: 'manual', site: 'manual', description: 'my text', notes: SECRET, extraLinks: [SECRET], sourceUrl: SECRET },
  { jobId: 'j01', title: 'ignored: the server holds j01', status: 'saved', keptByUser: true, outreach: { contacts: [{ name: SECRET }] }, tailoredAssets: { resumeMd: SECRET } },
]

describe('the browser\'s own rows in a page', () => {
  it('are in the list, in its order and its counts, and nothing says anything about their private fields', async () => {
    const extraRows = selectExtraRows(browserRows)
    const plain = (await get('mode=all')).json
    const { status, json, text } = await post({ mode: 'all', offset: 0, extraRows })
    expect(status).toBe(200)
    expect(json.total).toBe(plain.total + 2) // off1 and man1 are not on the server; j01 is
    expect(json.rows.map((r) => r.jobId)).toEqual(expect.arrayContaining(['off1', 'man1', 'j01']))
    expect(json.extra).toEqual({ sent: 3, notOnServer: 2 })
    expect(json.counts.stats.saved).toBeGreaterThan(plain.counts.stats.saved) // the status the owner set here counts
    expect(text).not.toContain(SECRET)
  })

  it('are stored nowhere: the next request without them is the plain list, and the data dir is untouched', async () => {
    const before = treeOf(server.root)
    const extraRows = selectExtraRows(browserRows)
    const withExtra = await post({ mode: 'all', offset: 0, extraRows })
    const after = await get('mode=all')
    expect(after.json.rows.map((r) => r.jobId)).not.toContain('off1')
    expect(after.json.total).toBe(withExtra.json.total - 2)
    expect(treeOf(server.root)).toEqual(before)
  })

  it('do not move the revision: it names the server\'s data', async () => {
    const plain = (await get('mode=all')).json
    const withExtra = (await post({ mode: 'all', extraRows: selectExtraRows(browserRows) })).json
    expect(withExtra.revision).toBe(plain.revision)
  })

  it('select-all across pages reaches them (ids mode)', async () => {
    const { json } = await post({ mode: 'all', ids: true, extraRows: selectExtraRows(browserRows) })
    expect(json.ids).toEqual(expect.arrayContaining(['off1', 'man1']))
    expect(json.selectableIds).toEqual(expect.arrayContaining(['off1', 'man1']))
    expect(json.extra.sent).toBe(3)
  })

  it('a browser-only ad cannot be opened from the server: it is not stored there, and the answer says where its text is', async () => {
    await post({ mode: 'all', extraRows: selectExtraRows(browserRows) })
    const res = await server.fetchFn('/api/jobs/list/ad?jobId=off1')
    expect(res.status).toBe(404)
  })
})

describe('what is not on the allowlist', () => {
  it.each(['notes', 'extraLinks', 'sourceUrl', 'outreach', 'tailoredAssets', 'aiInsights', 'llmFacts', 'engineShadow', 'anythingElse'])('%s in a row is a 400 that names the row and never echoes the value', async (field) => {
    const { status, json, text } = await post({ mode: 'all', extraRows: [{ jobId: 'off1', title: 'x', offList: true, [field]: SECRET }] })
    expect(status).toBe(400)
    expect(json.ok).toBe(false)
    expect(json.error).toContain('extraRows[0]')
    expect(json.error).toContain(field)
    expect(text).not.toContain(SECRET)
    expect(json).not.toHaveProperty('rows')
  })

  it('a tracking field outside the three is a 400', async () => {
    const { status, text } = await post({ mode: 'all', extraRows: [{ jobId: 'j01', ownerWork: true, applicationTracking: { applied: true, recruiterEmail: SECRET } }] })
    expect(status).toBe(400)
    expect(text).not.toContain(SECRET)
  })

  it.each([
    ['a bad id', [{ jobId: '../etc' }]],
    ['a repeated id', [{ jobId: 'a1' }, { jobId: 'a1' }]],
    ['rows that are not a list', { jobId: 'a1' }],
  ])('%s is a 400', async (_name, extraRows) => {
    expect((await post({ mode: 'all', extraRows })).status).toBe(400)
  })
})

describe('the request body', () => {
  it('over the limit is a 413 that says nothing was cut, and no list is made; the server carries on', async () => {
    const big = Array.from({ length: 700 }, (_, i) => ({ jobId: `big${i}`, title: `Big ${i}`, offList: true, description: 'x'.repeat(2000) }))
    const { status, json } = await post({ mode: 'all', extraRows: big })
    expect(status).toBe(413)
    expect(json.ok).toBe(false)
    expect(json.error).toMatch(/too many to send/)
    expect(json.error).toMatch(/Nothing was cut/)
    expect(json).not.toHaveProperty('rows')
    expect((await get('mode=all')).status).toBe(200)
  })

  it('that is not JSON is a 400', async () => {
    expect((await post(null, { raw: '{ not json' })).status).toBe(400)
  })

  it('takes the same parameters as the GET, refuses a limit, and needs the browser\'s day for the deadline sort', async () => {
    expect((await post({ mode: 'all', limit: 500 })).status).toBe(400)
    expect((await post({ mode: 'all', sort: { key: 'deadline', dir: 'asc' } })).status).toBe(400)
    expect((await post({ mode: 'all', sort: { key: 'deadline', dir: 'asc' }, today: Date.parse('2026-11-20T00:00:00Z') })).status).toBe(200)
    expect((await post({})).status).toBe(400)
    expect((await post({ mode: 'all', filters: { searchText: 'delivery' }, offset: 0 })).json.total).toBeGreaterThan(0)
    expect(SCORED.length).toBe(12)
  })
})
