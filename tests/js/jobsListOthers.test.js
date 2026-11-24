// What the screens other than the Jobs list read of the whole list (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P4 S4), against the real route over HTTP:
// the numbers with no rows (the Dashboard's cards, the AI context's totals), the scored rows of named ads (the browser brings the rows it holds up to date without
// loading the whole list), and what the AI context reads of the whole list.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SCORED, startListServer } from './setup/jobsListServer.js'

let server
beforeEach(async () => { server = await startListServer({ pageSize: 4 }) })
afterEach(() => server.close())

const post = (path, body) => server.fetchFn(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async (res) => ({ status: res.status, json: await res.json() }))

describe('the numbers with no rows', () => {
  it('are the list\'s counts with no page: no rows, no page size needed, the same numbers as the first page', async () => {
    const page = (await post('/api/jobs/list', { mode: 'all', offset: 0 })).json
    const { status, json } = await post('/api/jobs/list', { mode: 'all', countsOnly: true })
    expect(status).toBe(200)
    expect(json).not.toHaveProperty('rows')
    expect(json.total).toBe(page.total)
    expect(json.counts).toEqual(page.counts)
    expect(json.counts.stats.total).toBe(12)
  })

  it('take the same filters as a page', async () => {
    const { json } = await post('/api/jobs/list', { mode: 'all', countsOnly: true, filters: { searchText: 'delivery' } })
    expect(json.total).toBeGreaterThan(0)
    expect(json.total).toBeLessThan(13)
  })

  it('must be true or false', async () => {
    expect((await post('/api/jobs/list', { mode: 'all', countsOnly: 'yes' })).status).toBe(400)
  })
})

describe('the scored rows of named ads', () => {
  it('are slim, in the order asked, and the ads the scored list does not hold are named', async () => {
    const { status, json } = await post('/api/jobs/list/rows', { jobIds: ['j03', 'ledger-only-1', 'j01', 'gone-9'] })
    expect(status).toBe(200)
    expect(json.rows.map((r) => r.jobId)).toEqual(['j03', 'j01'])
    expect(json.missing).toEqual(['ledger-only-1', 'gone-9'])
    for (const row of json.rows) for (const field of ['description', 'llmFacts', 'engineShadow']) expect(row).not.toHaveProperty(field)
    expect(json.rows[0]).toMatchObject({ title: SCORED[3].title, matchScore: SCORED[3].matchScore })
    expect(typeof json.revision).toBe('string')
  })

  it.each([
    ['not a list', { jobIds: 'j01' }],
    ['a bad id', { jobIds: ['../x'] }],
    ['a repeated id', { jobIds: ['j01', 'j01'] }],
    ['no list', {}],
  ])('refuses %s with a 400', async (_name, body) => {
    expect((await post('/api/jobs/list/rows', body)).status).toBe(400)
  })

  it('takes POST only', async () => {
    expect((await server.fetchFn('/api/jobs/list/rows?jobIds=j01')).status).toBe(405)
    expect((await server.fetchFn('/api/jobs/list/context')).status).toBe(405)
  })
})

describe('what the AI context reads of the whole list', () => {
  it('the best-scored open ads in full, best first, and the best-scored ads\' missing skills', async () => {
    const { status, json } = await post('/api/jobs/list/context', {})
    expect(status).toBe(200)
    const scores = json.topJobs.map((job) => job.matchScore)
    expect(scores).toEqual([...scores].sort((a, b) => b - a))
    expect(json.topJobs.length).toBeLessThanOrEqual(10)
    expect(json.topJobs[0].description).toContain('The long ad text') // in full: the AI context summarises the text itself
    expect(Math.max(...SCORED.map((r) => r.matchScore))).toBe(scores[0])
    expect(json.skillGap).toHaveLength(12)
    expect(json.skillGap[0]).toEqual({ jobId: expect.any(String), matchScore: scores[0], missingSkills: [] })
  })

  it('an empty list gives empty answers, not an error', async () => {
    server.writeScored([])
    const { status, json } = await post('/api/jobs/list/context', {})
    expect(status).toBe(200)
    expect(json.topJobs).toEqual([])
    expect(json.skillGap).toEqual([])
  })
})
