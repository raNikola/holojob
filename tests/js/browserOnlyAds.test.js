// @vitest-environment jsdom
// An ad only this browser has (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b; the list is paged by the server, the browser-only rows are a bridge until P5):
// it appears in the paged list, it opens from the browser's own data (the server does not hold it), and an action on it is saved in the browser as before.
// An ad that is only a server row is read-only and is never written to the browser's list. Real server (HTTP, temp data dir), real browser store (jsdom).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ROUTE_ROWS, routeRow, startListServer } from './setup/jobsListServer.js'
import { buildListBody, fetchListPage, openAd, shownRows } from '../../src/modules/jobs/jobListClient.js'
import { JOBS_STORAGE_KEY, getDefaultJobsState, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { patchJob } from '../../src/modules/jobs/jobsStore.js'
import { resolveJob } from '../../src/modules/jobs/jobResolve.js'

const SECRET = 'PRIVATE-NOTE-9921'
const OFF = { jobId: 'off1', title: 'Gone Ad', company: 'Acme', location: 'Remote', jobUrl: 'https://x.example/off1', offList: true, status: 'saved', matchScore: 80, matchLabel: 'Good', priority: 'P1', applyRecommendation: 'Apply', isRemote: true, notes: SECRET }
const MAN = { jobId: 'man1', title: 'My own job', company: 'Me', location: 'Remote', jobUrl: 'https://y.example/man1', manualEntry: true, provider: 'manual', site: 'manual', description: 'my text', status: 'new', notes: SECRET, extraLinks: [SECRET], sourceUrl: `https://${SECRET}.example/` }
const WORKED = { jobId: 'j01', title: 'Held by the server', company: 'Co 1', jobUrl: 'https://x.example/1', status: 'saved', outreach: { status: 'sent', contacts: [{ name: SECRET }] } }

let server
let fetches
let fetchFn

beforeEach(async () => {
  localStorage.clear()
  // the ledger knows off1 (an earlier search found it); it knows nothing of the hand-entered job
  server = await startListServer({ pageSize: 50, routeRows: [...ROUTE_ROWS, routeRow(OFF, 'older_key')] })
  saveJobs({ ...getDefaultJobsState(), jobs: [OFF, MAN, WORKED] })
  fetches = []
  fetchFn = (url, options) => { fetches.push(url); return server.fetchFn(url, options) }
})
afterEach(async () => {
  vi.restoreAllMocks()
  await server.close()
})

const storedNow = () => loadJobs().jobs
const bodyNow = (extra = {}) => buildListBody({ stored: storedNow(), mode: 'all', ...extra })

describe('a browser-only ad in the paged list', () => {
  it('appears in the list, shown from the browser\'s own copy with the server\'s class laid over it', async () => {
    const body = bodyNow()
    const answer = await fetchListPage(body, fetchFn)
    expect(answer.ok).toBe(true)
    const ids = answer.page.rows.map((r) => r.jobId)
    expect(ids).toEqual(expect.arrayContaining(['off1', 'man1', 'j01']))
    const rows = shownRows(answer.page, storedNow())
    const manual = rows.find((r) => r.jobId === 'man1')
    expect(manual.notes).toBe(SECRET) // the owner's own copy, in the owner's browser
    expect(manual.title).toBe('My own job')
    const gone = rows.find((r) => r.jobId === 'off1')
    expect(gone).toMatchObject({ notes: SECRET, title: 'Gone Ad', class: 'older_key' }) // the browser's copy, with the server's word on where it stands
    // a row the server holds is the server's (its title, score and tier), with the owner's own fields from the browser's copy laid over it
    const held = rows.find((r) => r.jobId === 'j01')
    expect(held.title).toBe(answer.page.rows.find((r) => r.jobId === 'j01').title)
    expect(held.title).not.toBe(WORKED.title)
    expect(held.outreach).toEqual(WORKED.outreach)
    expect(held.serverOnly).toBeUndefined()
    // an ad only the server holds is marked: read-only until Keep
    expect(rows.find((r) => r.jobId === 'j05').serverOnly).toBe(true)
  })

  it('goes to the server without a word of its notes, links, source address or outreach', async () => {
    const body = bodyNow()
    expect(JSON.stringify(body)).not.toContain(SECRET)
    const answer = await fetchListPage(body, fetchFn)
    expect(JSON.stringify(answer.page)).not.toContain(SECRET)
    expect(answer.page.extra).toEqual({ sent: 3, notOnServer: 2 })
  })

  const manyRows = (count, bytes) => Array.from({ length: count }, (_, i) => ({ jobId: `big${i}`, title: `Big ${i}`, offList: true, description: 'x'.repeat(bytes), status: 'saved' }))

  it('600 ads with long texts are one ordinary request: the cap is hard to reach', async () => {
    const answer = await fetchListPage(buildListBody({ stored: [...storedNow(), ...manyRows(600, 9500)], mode: 'all' }), fetchFn)
    expect(answer.ok).toBe(true)
    expect(answer.page.extra.sent).toBe(603)
  })

  it('past the cap it is an error the owner is shown, with the row count and what to do, never a shorter list', async () => {
    const stored = [...storedNow(), ...manyRows(600, 9500)]
    // a text search sends the ads' text too, and 600 of them are over the cap
    const answer = await fetchListPage(buildListBody({ stored, mode: 'all', filters: { searchText: 'engineer' } }), fetchFn)
    expect(answer.ok).toBe(false)
    expect(answer.tooLarge).toBe(true)
    expect(answer.rowCount).toBe(603)
    expect(answer.message).toContain('603 ads')
    expect(answer.message).toContain('1 hand-entered, 601 that left the list, 1 with your work on a server ad')
    expect(answer.message).toMatch(/Nothing was cut and no list was made/)
    expect(answer.message).toMatch(/delete hand-entered jobs/i)
    expect(answer.message).toMatch(/1024 KB/)
    expect(answer).not.toHaveProperty('page')
  })
})

describe('opening an ad', () => {
  it('a browser-only ad opens from local data, with no request to the server', async () => {
    for (const jobId of ['off1', 'man1', 'j01']) {
      const opened = await openAd({ jobId, stored: storedNow(), fetchFn })
      expect(opened.source).toBe('local')
      expect(opened.readOnly).toBe(false)
      expect(opened.row.jobId).toBe(jobId)
    }
    expect(fetches).toEqual([])
    // and Job Details reads it as it always has: a stored row, with somewhere to write
    expect(resolveJob({ stored: storedNow().find((j) => j.jobId === 'off1') })).toMatchObject({ source: 'stored', readOnly: false, notInLatest: true })
  })

  it('an ad that is only a server row opens from the server, read-only; one with no scored row is left to the ledger fallback', async () => {
    const opened = await openAd({ jobId: 'j05', stored: storedNow(), fetchFn })
    expect(opened).toMatchObject({ source: 'server', readOnly: true })
    expect(opened.row.description).toContain('The long ad text number 5')
    expect(await openAd({ jobId: 'ledger-only-1', stored: storedNow(), fetchFn })).toMatchObject({ source: 'none', status: 404 })
  })
})

describe('an action on a browser-only ad', () => {
  it('persists in the browser as before, and the next page of the list shows it', async () => {
    const before = (await fetchListPage(bodyNow(), fetchFn)).page
    expect(patchJob('off1', { status: 'rejected' })).toMatchObject({ ok: true, changed: true })
    expect(storedNow().find((j) => j.jobId === 'off1').status).toBe('rejected') // saved in this browser
    const after = (await fetchListPage(bodyNow(), fetchFn)).page
    expect(after.rows.find((r) => r.jobId === 'off1').status).toBe('rejected')
    expect(after.counts.stats.rejected).toBe(before.counts.stats.rejected) // off1 is off the list: not counted, as ever
    expect(after.total).toBe(before.total)
  })

  it('notes, outreach and tailoring on it stay in the browser; the server only learns the ad was worked on', async () => {
    expect(patchJob('man1', { notes: 'edited private note', tailoredAssets: { resumeMd: '# private cv' }, outreach: { status: 'sent', contacts: [{ name: 'Private Person' }] } })).toMatchObject({ ok: true })
    const stored = storedNow().find((j) => j.jobId === 'man1')
    expect(stored).toMatchObject({ notes: 'edited private note', tailoredAssets: { resumeMd: '# private cv' } })
    const body = bodyNow()
    const sent = JSON.stringify(body)
    for (const word of ['edited private note', '# private cv', 'Private Person']) expect(sent).not.toContain(word)
    expect(body.extraRows.find((r) => r.jobId === 'man1').ownerWork).toBe(true)
    expect((await fetchListPage(body, fetchFn)).ok).toBe(true)
  })
})

describe('an ad that is only a server row', () => {
  it('is never written to the browser\'s list: listing, paging and opening it write no storage at all', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const before = localStorage.getItem(JOBS_STORAGE_KEY)
    const first = await fetchListPage(bodyNow({ offset: 0 }), fetchFn)
    await fetchListPage(bodyNow({ offset: first.page.nextOffset, revision: first.page.revision }), fetchFn)
    shownRows(first.page, storedNow())
    await openAd({ jobId: 'j05', stored: storedNow(), fetchFn })
    await openAd({ jobId: 'ledger-only-1', stored: storedNow(), fetchFn })
    expect(setItem).not.toHaveBeenCalled()
    expect(localStorage.getItem(JOBS_STORAGE_KEY)).toBe(before)
    expect(storedNow().map((j) => j.jobId)).toEqual(['off1', 'man1', 'j01'])
    // every server-only row of the page is read-only
    for (const id of ROUTE_ROWS.map((r) => r.jobId).filter((id) => !['off1', 'man1', 'j01'].includes(id))) {
      expect(resolveJob({ fileJob: { jobId: id } }).readOnly).toBe(true)
    }
  })
})
