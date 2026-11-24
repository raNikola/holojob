// Bringing the rows the browser holds up to date with the last scoring, without loading the whole scored list (src/modules/jobs/workedRows.js; P3 S6 / P4).
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SCORED, startListServer } from './setup/jobsListServer.js'
import { applyRowsRefresh, refreshWorkedRows } from '../../src/modules/jobs/workedRows.js'

const mine = (extra = {}) => ({ jobId: 'j01', title: 'Old title', company: 'Co 1', jobUrl: 'https://x.example/1', matchScore: 10, matchLabel: 'Weak', status: 'new', ...extra })
const fresh = (extra = {}) => ({ jobId: 'j01', title: 'New title', company: 'Co 1', jobUrl: 'https://x.example/1', matchScore: 85, matchLabel: 'Strong', description: 'New text', ...extra })

describe('applyRowsRefresh', () => {
  it('takes the new pipeline fields and keeps everything that is the owner\'s', () => {
    const owned = mine({ status: 'saved', keptByUser: true, keptAt: '2026-11-01', tailoredAssets: { resumeMd: '# cv' }, aiInsights: { summary: 's' }, outreach: { status: 'sent', contacts: [{ name: 'Ann' }] }, notes: 'a private note', extraLinks: ['https://l.example'], applicationTracking: { applied: true } })
    const [row] = applyRowsRefresh([owned], { rows: [fresh()], missing: [] })
    expect(row).toMatchObject({ title: 'New title', matchScore: 85, matchLabel: 'Strong' })
    expect(row).toMatchObject({ status: 'saved', keptByUser: true, tailoredAssets: { resumeMd: '# cv' }, aiInsights: { summary: 's' }, outreach: { status: 'sent', contacts: [{ name: 'Ann' }] }, notes: 'a private note', extraLinks: ['https://l.example'], applicationTracking: { applied: true } })
  })

  it('an ad the scored list no longer holds is off the list if the owner worked on it, and gone if not; a hand-entered job always stays', () => {
    const worked = mine({ jobId: 'w', status: 'saved' })
    const plain = mine({ jobId: 'p', jobUrl: 'https://x.example/p' })
    const manual = mine({ jobId: 'm', jobUrl: 'https://x.example/m', manualEntry: true })
    const out = applyRowsRefresh([worked, plain, manual], { rows: [], missing: ['w', 'p', 'm'] })
    expect(out.map((job) => job.jobId)).toEqual(['w', 'm'])
    expect(out[0].offList).toBe(true)
    expect(out[1].offList).toBeUndefined()
  })

  it('an off-list ad that is back in the scored list is on the list again', () => {
    const [row] = applyRowsRefresh([mine({ status: 'saved', offList: true })], { rows: [fresh()], missing: [] })
    expect(row.offList).toBeUndefined()
    expect(row.status).toBe('saved')
  })

  it('keeps the ad\'s text when the answer brings none: a kept ad\'s text exists only here and in the ledger', () => {
    const [row] = applyRowsRefresh([mine({ status: 'saved', description: 'My only copy of the text' })], { rows: [fresh({ description: '' })], missing: [] })
    expect(row.description).toBe('My only copy of the text')
    const [replaced] = applyRowsRefresh([mine({ status: 'saved', description: 'Old text' })], { rows: [fresh({ description: 'New text' })], missing: [] })
    expect(replaced.description).toBe('New text')
  })

  it('leaves alone a row the answer does not name, and changes none of its inputs', () => {
    const other = mine({ jobId: 'other', jobUrl: 'https://x.example/other', status: 'saved' })
    const before = JSON.stringify([other, mine()])
    const out = applyRowsRefresh(Object.freeze([Object.freeze(other), Object.freeze(mine())]), { rows: [fresh()], missing: [] })
    expect(out[0]).toBe(other)
    expect(JSON.stringify([other, mine()])).toBe(before)
  })
})

describe('refreshWorkedRows against the real route', () => {
  let server
  beforeEach(async () => { server = await startListServer({ pageSize: 4 }) })
  afterEach(() => server.close())

  it('updates the rows the browser holds from the scored list and marks the ones it no longer holds', async () => {
    const state = {
      meta: null, importedAt: 'first', filters: {},
      jobs: [
        { jobId: 'j01', title: 'Stale title', company: 'Stale', jobUrl: SCORED[1].jobUrl, matchScore: 1, status: 'saved', notes: 'private' },
        { jobId: 'gone-7', title: 'Left the list', jobUrl: 'https://x.example/gone-7', status: 'saved', matchScore: 50 },
        { jobId: 'plain-8', title: 'Never worked on', jobUrl: 'https://x.example/plain-8', status: 'new' },
      ],
    }
    const { state: next, changed } = await refreshWorkedRows(state, server.fetchFn)
    expect(changed).toBe(true)
    expect(next.jobs.map((job) => job.jobId)).toEqual(['j01', 'gone-7'])
    expect(next.jobs[0]).toMatchObject({ title: SCORED[1].title, matchScore: SCORED[1].matchScore, status: 'saved', notes: 'private' })
    expect(next.jobs[1]).toMatchObject({ offList: true, status: 'saved' })
    expect(next.importedAt).not.toBe('first')
    expect(next.meta).toMatchObject({ generatedAt: expect.any(String) })
  })

  it('asks nothing for an empty list', async () => {
    const calls = []
    const { state, changed } = await refreshWorkedRows({ jobs: [], meta: null }, (...args) => { calls.push(args); return server.fetchFn(...args) })
    expect(changed).toBe(false)
    expect(state.jobs).toEqual([])
    expect(calls).toEqual([])
  })

  it('a failed refresh changes nothing and says why', async () => {
    const state = { jobs: [mine()], meta: null, importedAt: 'first' }
    const down = await refreshWorkedRows(state, () => Promise.reject(new Error('down')))
    expect(down.error).toMatch(/down/)
    expect(down).not.toHaveProperty('state')
    const refused = await refreshWorkedRows(state, () => Promise.resolve({ ok: false, status: 503, json: async () => ({ message: 'cannot be read' }) }))
    expect(refused.error).toBe('cannot be read')
  })
})
