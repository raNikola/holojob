// @vitest-environment jsdom
// Real clicks on the real Jobs screen (slices S5e3b, S5e3c). The pure rules are in jobTable.test.js and jobListView.test.js.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ago, countWrites, mountScreen, routeAnswer, routeRow, settle, storedJob, stubServer, viewport } from './setup/jobsScreenHarness.js'

const STORED = [storedJob('s1', { status: 'saved', matchScore: 80, matchLabel: 'Strong', outreach: { contacts: [{ name: 'x' }] } }), storedJob('s2')]
const ROUTE = [
  routeRow('s1'), routeRow('s2'), routeRow('abs', 'absent', { absentSince: ago(2) }), routeRow('old', 'absent', { lastSeen: ago(30), absentSince: ago(20) }), routeRow('key', 'older_key'), routeRow('cl', 'closed'),
  routeRow('fil', 'filtered', { from: 'filtered', title: 'Filtered Chef', reason: "Filtered out: Title didn't match" }),
]
const good = () => routeAnswer(ROUTE)
const failed = () => ({ status: 503, body: { ok: false, error: 'view_unrecoverable', message: 'cannot be read' } })

// Each test loads the whole screen fresh, as after a page load; that alone can pass the default 5 s when the full suite runs alongside.
vi.setConfig({ testTimeout: 60000, hookTimeout: 60000 })

let screen
beforeEach(() => viewport(true))
afterEach(async () => {
  await screen?.unmount()
  screen = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.doUnmock('../../src/modules/jobs/useRescrapeRun')
})

// The same tests run on both lists: the one the browser works out from its own rows (demo data, no API) and the one the server pages
// (docs/redesign/JOBS_LIST_SERVER_PLAN.md). Where the two are meant to differ, a test says so and runs on one.
let serverMode = false
const stubList = (options = {}) => stubServer({ ...options, listServer: serverMode })
const mountList = (options = {}) => mountScreen({ ...options, server: serverMode })

describe.each([['local', false], ['server', true]])('the %s list', (_name, on) => {
beforeEach(() => { serverMode = on })

const many = (count) => Array.from({ length: count }, (_, i) => storedJob(`j${String(i).padStart(4, '0')}`, { title: `Job ${i}`, matchScore: 50 }))

// The table pages a long list through the server (the list without a server has no page size: it is the demo data or the few ads the owner worked on).
;(on ? describe : describe.skip)('the table on a long list', () => {
  it('sorts the whole list, then shows a batch', async () => {
    stubList({ route: () => routeAnswer([]) })
    const jobs = many(350)
    jobs[349] = { ...jobs[349], matchScore: 80, title: 'The best ad' } // the only Strong fit: the first tier comes first whatever its place in the list
    screen = await mountList({ stored: jobs })
    expect(screen.rows()).toHaveLength(100)
    expect(screen.rows()[0].textContent).toContain('The best ad')
    expect(screen.text()).toContain('Showing 100 of 350')
    await screen.click(screen.button(/Show 100 more/))
    expect(screen.rows()).toHaveLength(200)
  })

  it('selection survives Show more and a re-sort, and neither writes storage', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(350) })
    const raw = screen.raw()
    const writes = countWrites(screen.key)
    await screen.click(screen.rows()[0].querySelector('input[type=checkbox]'))
    expect(screen.text()).toContain('1 selected')
    await screen.click(screen.button(/Show 100 more/))
    expect(screen.rows()).toHaveLength(200)
    expect(screen.text()).toContain('1 selected')
    await screen.click([...screen.container.querySelectorAll('th button')].find((b) => /title/i.test(b.textContent)))
    expect(screen.rows()).toHaveLength(100)
    expect(screen.text()).toContain('1 selected')
    expect(writes()).toBe(0)
    expect(screen.raw()).toBe(raw)
  })

  it('a filter change resets the selection and the batch, keeps its persistence, and the stored jobs stay byte-identical', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(150) })
    const before = JSON.stringify(screen.storedJobs())
    await screen.click(screen.rows()[0].querySelector('input[type=checkbox]'))
    await screen.click(screen.button(/Show 50 more/))
    expect(screen.rows()).toHaveLength(150)
    await screen.type(screen.container.querySelector('#filter-search'), 'Job')
    expect(screen.rows()).toHaveLength(100)
    expect(screen.text()).not.toContain('1 selected')
    expect(JSON.parse(screen.raw()).filters.searchText).toBe('Job')
    expect(JSON.stringify(screen.storedJobs())).toBe(before)
  })

  it('a status the server refuses is not saved, here or in the browser, and says so', async () => {
    stubList({})
    const served = globalThis.fetch
    vi.stubGlobal('fetch', async (url, options = {}) => (String(url) === '/api/jobs/state' && options.method === 'POST'
      ? { ok: false, status: 400, json: async () => ({ error: 'status is not valid' }) }
      : served(url, options)))
    screen = await mountList({ stored: many(5) })
    await screen.click(screen.rows()[0].querySelector('button[aria-label="Save"]'))
    await settle()
    expect(screen.storedJobs().filter((j) => j.status === 'saved')).toHaveLength(0)
    expect(screen.text()).toContain('The status was not saved: status is not valid')
  })

  it('a status change with the API unreachable keeps the old status and shows the error', async () => {
    stubList({ health: false })
    screen = await mountList({ stored: many(5) })
    const before = JSON.stringify(screen.storedJobs())
    await screen.click(screen.rows()[0].querySelector('button[aria-label="Save"]'))
    await settle()
    expect(JSON.stringify(screen.storedJobs())).toBe(before)
    expect(screen.text()).toContain('The status was not saved: Job statuses need the local API server')
  })

  it('a row\'s new status keeps the rows loaded', async () => {
    stubList({})
    screen = await mountList({ stored: many(250) })
    await screen.click(screen.button(/Show 100 more/))
    await screen.click(screen.rows()[150].querySelector('button[aria-label="Save"]'))
    expect(screen.rows()).toHaveLength(200)
    expect(screen.storedJobs().filter((j) => j.status === 'saved')).toHaveLength(1)
  })

  it('bulk status acts on the selected stored rows', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(3) })
    await screen.click(screen.rows()[0].querySelector('input[type=checkbox]'))
    await screen.click(screen.button(/^Mark saved$/))
    await settle()
    expect(screen.storedJobs().filter((j) => j.status === 'saved')).toHaveLength(1)
  })

  it('the keyboard keeps its place when the last Show more button goes', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(150) })
    const button = screen.button(/Show 50 more/)
    button.focus()
    await screen.click(button)
    expect(document.activeElement?.getAttribute('role')).toBe('status')
  })

  it('the Fit tier column is judged on the whole list, also after a re-sort moves the only score out of the batch', async () => {
    stubList({ route: () => routeAnswer([]) })
    const jobs = many(150).map((j, i) => ({ ...j, matchScore: i === 0 ? 5 : undefined, title: i === 0 ? 'ZZZ last by title' : j.title }))
    screen = await mountList({ stored: jobs })
    await screen.click([...screen.container.querySelectorAll('th button')].find((b) => /title/i.test(b.textContent)))
    expect(screen.text()).not.toContain('ZZZ last by title')
    expect([...screen.container.querySelectorAll('th button')].some((b) => /tier/i.test(b.textContent))).toBe(true)
  })

})

describe('Active and All', () => {
  it('by default Active leaves out the ad the board no longer lists, says how many, and the filter brings it back', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED, filters: { showNotOnBoard: false } })
    expect(screen.rows()).toHaveLength(2)
    expect(screen.text()).not.toContain('why absent')
    expect(screen.text()).toContain("1 ad is not on the company's board")
    await screen.click(screen.box(/Show ads not on the company's board/))
    expect(screen.rows()).toHaveLength(3)
    expect(screen.text()).toContain('why absent')
  })

  it('the toggle, the class filter and the 14-day filter change the list and write nothing', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    const raw = screen.raw()
    const writes = countWrites(screen.key)
    await screen.click(screen.button(/^All$/))
    expect(screen.rows()).toHaveLength(7)
    expect(screen.text()).toContain('Search settings changed')
    expect(screen.text()).toContain('does not match the ad text')
    await screen.click(screen.box(/Closed \(1\)/))
    expect(screen.rows()).toHaveLength(1)
    await screen.click(screen.box(/Closed \(1\)/))
    expect(screen.rows()).toHaveLength(7)
    await screen.click(screen.box(/Seen in the last 14 days/))
    expect(screen.rows()).toHaveLength(6)
    await screen.click(screen.box(/Seen in the last 14 days/))
    await screen.click(screen.button(/^Active$/))
    expect(screen.rows()).toHaveLength(3)
    expect(writes()).toBe(0)
    expect(screen.raw()).toBe(raw)
    expect(screen.raw()).not.toMatch(/"class"|"serverOnly"|"copyGroup"/)
  })

  it('the Active period is the one in Settings: a longer one keeps an older absent ad, none known keeps no absent ad, and the label names it', async () => {
    stubServer({ route: good, windowDays: 40 })
    screen = await mountScreen({ stored: STORED })
    expect(screen.rows()).toHaveLength(4) // s1, s2, the absent ad seen yesterday and the one seen 30 days ago
    await screen.click(screen.button(/^All$/))
    await settle()
    expect(screen.rows()).toHaveLength(7)
    expect(screen.box(/Seen in the last 40 days/)).toBeTruthy()
    await screen.unmount()

    // No period known: the server's list is not made (the Active period is Settings', and no number is made up). The saved rows are shown, with the reason.
    stubServer({ route: good, windowDays: null })
    screen = await mountScreen({ stored: STORED })
    await settle()
    expect(screen.rows()).toHaveLength(2)
    expect(screen.text()).toContain('activeWindowDays')
    await screen.click(screen.button(/^All$/))
    await settle()
    expect(screen.rows()).toHaveLength(2)
  })

  it('a change of mode or class resets the selection', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.row('T s2').querySelector('input[type=checkbox]'))
    expect(screen.text()).toContain('1 selected')
    await screen.click(screen.button(/^All$/))
    expect(screen.text()).not.toContain('1 selected')
  })

  it('the old filter is off and disabled in a composed list, and works on today\'s list', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/More filters/) ?? screen.container)
    expect(screen.box(/Show jobs absent/)?.disabled).toBe(true)
    await screen.unmount()
    stubList({ health: false })
    screen = await mountList({ stored: [...STORED, storedJob('off', { offList: true, status: 'saved' })] })
    expect(screen.rows()).toHaveLength(2)
    await screen.click(screen.button(/More filters/) ?? screen.container)
    expect(screen.box(/Show jobs absent/)?.disabled).toBe(false)
    await screen.click(screen.box(/Show jobs absent/))
    expect(screen.rows()).toHaveLength(3)
  })

  it('the Analytics numbers are the same with the route on and off', async () => {
    const scored = () => ({ meta: {}, jobs: STORED })
    stubList({ route: good, scored })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^Analytics$/))
    await settle()
    const on = screen.text()
    await screen.unmount()
    stubList({ route: failed, scored })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^Analytics$/))
    await settle()
    expect(screen.text()).toBe(on)
  })
})

describe('a Stale ad', () => {
  const STALE = routeRow('old1', 'stale', { title: 'A stale ad', reason: 'No sighting for 40 days and 3 successful runs of this search. Last seen 2026-09-25' })
  const stale = () => routeAnswer([routeRow('s1'), STALE])

  it('is out of Active, in All with its badge and counts, and under the Stale filter', async () => {
    stubList({ route: stale })
    screen = await mountList({ stored: [storedJob('s1')] })
    expect(screen.row('A stale ad')).toBeUndefined()
    await screen.click(screen.button(/^All$/))
    expect(screen.row('A stale ad').textContent).toContain('Stale')
    expect(screen.row('A stale ad').textContent).toContain('No sighting for 40 days and 3 successful runs')
    await screen.click(screen.box(/Stale \(1\)/))
    expect(screen.rows()).toHaveLength(1)
  })

  it('stays in Active with work on it', async () => {
    stubList({ route: stale })
    screen = await mountList({ stored: [storedJob('s1'), storedJob('old1', { status: 'saved', offList: true })] })
    expect(screen.row('A stale ad').textContent).toContain('Stale')
    expect(screen.row('A stale ad').querySelector('button[aria-label="Reject"]').disabled).toBe(false)
  })
})

describe('when the route does not give a whole list', () => {
  it('a 503 keeps the local list, says so and offers another try', async () => {
    const server = stubList({ route: failed })
    screen = await mountList({ stored: STORED })
    expect(screen.rows()).toHaveLength(2)
    expect(screen.text()).toContain('cannot be read')
    expect(screen.text()).toContain('nothing was changed')
    const raw = screen.raw()
    await screen.click(screen.button(/^All$/))
    expect(screen.text()).toContain('This list is incomplete')
    expect(screen.rows()).toHaveLength(2)
    const calls = server.allCalls
    await screen.click(screen.button(/Try again/))
    await settle()
    expect(server.allCalls).toBe(calls + 1)
    expect(screen.raw()).toBe(raw)
  })

  it('a missing filtered file says the list is incomplete in All', async () => {
    stubList({ route: () => routeAnswer([routeRow('s1')], 'missing') })
    screen = await mountList({ stored: STORED })
    expect(screen.text()).not.toContain('This list is incomplete')
    await screen.click(screen.button(/^All$/))
    expect(screen.text()).toContain('This list is incomplete: filtered ads could not be read')
  })

  it('an empty answer never clears stored rows', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: STORED })
    expect(screen.rows()).toHaveLength(2)
    expect(screen.storedJobs()).toHaveLength(2)
  })

  it('no API: today\'s list, no toggle, and the route is never asked', async () => {
    const server = stubList({ health: false })
    screen = await mountList({ stored: STORED })
    expect(screen.button(/^All$/)).toBeUndefined()
    expect(server.allCalls).toBe(0)
    expect(screen.rows()).toHaveLength(2)
  })

  // The browser's own application store feeds only the list it works out itself; the server's list is made with the server's store.
  ;(on ? it.skip : it)('a failed application store is flagged, and copies stay apart', async () => {
    stubList({ route: () => routeAnswer([routeRow('a', 'absent', { copyGroup: 'g' }), routeRow('b', 'absent', { copyGroup: 'g' })]) })
    const real = globalThis.fetch
    vi.stubGlobal('fetch', async (url, options) => (String(url).startsWith('/api/applications') ? { ok: false, status: 500, json: async () => ({ error: 'no' }) } : real(url, options)))
    screen = await mountList({ stored: [] })
    await settle()
    expect(screen.rows()).toHaveLength(2)
    expect(screen.text()).toContain('Your applications could not be loaded')
  })
})

describe('asking the route again', () => {
  it('after Re-score', async () => {
    const server = stubList({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountList({ stored: STORED })
    const before = server.allCalls
    await screen.click(screen.button(/^Re-score$/))
    await settle()
    expect(server.allCalls).toBeGreaterThan(before)
  })

  it.each(['done', 'failed'])('after a Re-scrape that ended %s', async (status) => {
    let finished
    vi.doMock('../../src/modules/jobs/useRescrapeRun', () => ({ useRescrapeRun: ({ onFinished }) => { finished = onFinished; return { start() {}, view: { active: false } } } }))
    const server = stubList({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountList({ stored: STORED })
    const before = server.allCalls
    await screen.click(screen.container)
    await (await import('react')).act(async () => { await finished({ status }) })
    await settle()
    expect(server.allCalls).toBeGreaterThan(before)
  })
})

describe('a Re-scrape that found nothing usable', () => {
  it.each(['failed', 'skipped'])('says the list was not changed (%s) and does not re-import the scored file', async (status) => {
    let finished
    vi.doMock('../../src/modules/jobs/useRescrapeRun', () => ({ useRescrapeRun: ({ onFinished }) => { finished = onFinished; return { start() {}, view: { active: false } } } }))
    const server = stubList({ route: good, scored: () => ({ meta: {}, jobs: [{ jobId: 'from-file', title: 'From file' }] }) })
    screen = await mountList({ stored: STORED })
    const before = screen.raw()
    await screen.click(screen.container)
    await (await import('react')).act(async () => { await finished({ status, import: { kind: 'nothing', nothingSaved: 'no_usable_source' } }) })
    await settle()
    expect(screen.text()).toContain('Re-scrape found nothing usable: no source gave a usable result, so the list was not changed.')
    expect(screen.text()).not.toContain('Re-scrape failed')
    expect(screen.raw()).toBe(before)
    expect(server.allCalls).toBeGreaterThan(0)
  })
})

describe('rows only the server holds', () => {
  it('a filtered row has no checkbox and opens nothing', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    const row = screen.row('Filtered Chef')
    expect(row.querySelector('input[type=checkbox]')).toBeNull()
    expect(row.querySelector('a[href="https://x.example/fil"]')).not.toBeNull()
    await screen.click(row)
    expect(screen.text()).not.toContain('Open full details')
  })

  it('a filtered card opens nothing either', async () => {
    viewport(false)
    stubList({ route: () => routeAnswer([routeRow('fil', 'filtered', { from: 'filtered', title: 'Filtered Chef' })]) })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    const card = [...screen.container.querySelectorAll('div.rounded-xl')].find((d) => d.textContent.includes('Filtered Chef') && d.textContent.includes('Open ad'))
    await screen.click(card)
    expect(screen.text()).not.toContain('Open full details')
  })

  it('Add job opens the form prefilled and saves nothing', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    const raw = screen.raw()
    const writes = countWrites(screen.key)
    await screen.click(screen.button(/^Add job$/, screen.row('Filtered Chef')))
    const values = [...screen.container.querySelectorAll('input')].map((i) => i.value)
    expect(values).toEqual(expect.arrayContaining(['Filtered Chef', 'Acme', 'https://x.example/fil']))
    expect(writes()).toBe(0)
    expect(screen.raw()).toBe(raw)
  })

  it('the plain Add job after it starts empty', async () => {
    stubList({ route: good })
    screen = await mountList({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    await screen.click(screen.button(/^Add job$/, screen.row('Filtered Chef')))
    await screen.click(screen.button(/^Cancel$/))
    await screen.click(screen.button(/^Add job$/))
    expect([...screen.container.querySelectorAll('input')].map((i) => i.value)).not.toContain('Filtered Chef')
  })

  it('opening the drawer of a server-only row stores nothing, and its ad text comes from the ledger', async () => {
    stubList({ route: good, ledger: (jobId) => ({ jobId, job: { jobId, title: 'T abs', description: 'THE LEDGER AD TEXT' }, firstSeen: ago(30), lastSeen: ago(1), closedAt: null }) })
    screen = await mountList({ stored: STORED })
    const raw = screen.raw()
    const writes = countWrites(screen.key)
    await screen.click(screen.row('T abs'))
    await settle()
    expect(screen.text()).toContain('Open full details')
    expect(screen.text()).toContain('THE LEDGER AD TEXT')
    expect(writes()).toBe(0)
    expect(screen.raw()).toBe(raw)
    expect(screen.storedJobs()).toHaveLength(2)
  })
})

// What only the server's list does (these run on it alone): pages from the server, select-all across pages, a list that moved, a request that is too large,
// and the browser's own rows in the list.
describe('the server\'s list on the screen', () => {
  const it2 = on ? it : it.skip
  const offList = (n, extra = {}) => storedJob(`off${n}`, { title: `Left ad ${n}`, offList: true, status: 'saved', matchScore: 60, matchLabel: 'Good', priority: 'P2', applyRecommendation: 'Maybe', ...extra })

  it2('Show more asks the server for the next page, at the server\'s page size', async () => {
    const server = stubList({ route: () => routeAnswer([]), pageSize: 100 })
    screen = await mountList({ stored: many(350) })
    expect(screen.rows()).toHaveLength(100)
    expect(screen.text()).toContain('Showing 100 of 350')
    await screen.click(screen.button(/Show 100 more/))
    await settle()
    expect(screen.rows()).toHaveLength(200)
    // (the rows the browser holds are brought up to date when the screen opens, which reads the list once more from the first page)
    expect(server.listCalls.map((call) => call.offset).slice(-2)).toEqual([0, 100])
    expect(server.listCalls.every((call) => call.offset === 0 || call.offset === 100)).toBe(true)
  })

  it2('select all reaches the ads of every page, not only the ones shown', async () => {
    stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(250) })
    expect(screen.rows()).toHaveLength(100)
    await screen.click(screen.container.querySelector('thead input[type=checkbox]'))
    await settle()
    expect(screen.text()).toContain('250 selected')
  })

  it2('a list that changed under the page is loaded again from the start, with a notice', async () => {
    const server = stubList({ route: () => routeAnswer([]) })
    screen = await mountList({ stored: many(250) })
    server.stateWrites.push({ key: 'other', patch: { status: 'saved' } }) // the server's data moved
    await screen.click(screen.button(/Show 100 more/))
    await settle()
    expect(screen.text()).toContain('The list changed while you were looking at it')
    expect(screen.rows()).toHaveLength(100) // from the start again, not 200 spliced from two states
  })

  it2('a list request that is too large says how many ads and what to do, and the saved rows stay', async () => {
    stubList({ route: () => routeAnswer([]) })
    const heavy = Array.from({ length: 120 }, (_, i) => offList(i, { description: 'x'.repeat(9500) }))
    screen = await mountList({ stored: [storedJob('s1'), ...heavy] })
    expect(screen.rows().length).toBeGreaterThan(0) // 120 rows without their texts are an ordinary request
    await screen.type(screen.container.querySelector('input[type=search], input[placeholder*="earch"]'), 'ad') // a text search sends the texts too
    await settle()
    expect(screen.text()).toContain('120 ads')
    expect(screen.text()).toContain('Nothing was cut and no list was made')
    expect(screen.text()).toMatch(/delete hand-entered jobs/i)
  })

  it2('the whole scored list is never loaded into the browser: on load, after a Re-score, and the browser keeps only the rows it holds', async () => {
    const wide = Array.from({ length: 300 }, (_, i) => storedJob(`wide${String(i).padStart(3, '0')}`, { title: `Wide ${i}`, matchScore: 50 + (i % 40) }))
    const mineRow = storedJob('wide007', { title: 'Old title', status: 'saved', matchScore: 1, notes: 'private' })
    const server = stubList({ route: () => routeAnswer([]), scoredRows: wide, scored: () => ({ meta: {}, jobs: wide }) })
    screen = await mountList({ stored: [mineRow] })
    await settle()
    expect(server.paths).not.toContain('/api/scoring/jobs') // the scored file is not fetched
    expect(screen.storedJobs().map((j) => j.jobId)).toEqual(['wide007']) // 300 rows on the server, one in the browser
    expect(screen.storedJobs()[0]).toMatchObject({ title: 'Wide 7', matchScore: 57, status: 'saved', notes: 'private' }) // its score is the server's, the owner's work is kept
    await screen.click(screen.button(/^Re-score$/))
    await settle()
    expect(server.paths).not.toContain('/api/scoring/jobs')
    expect(screen.storedJobs().map((j) => j.jobId)).toEqual(['wide007'])
  })

  it2('the rows the browser holds follow a new scoring; an ad that left the list is off the list, not lost', async () => {
    const before = [storedJob('a1', { title: 'Before' }), storedJob('a2', { title: 'Will go' })]
    const after = [storedJob('a1', { title: 'After', matchScore: 90 })]
    let scored = before
    stubList({ route: () => routeAnswer([]), scoredRows: null, scored: () => ({ meta: {}, jobs: scored }) })
    screen = await mountList({ stored: [{ ...before[0], status: 'saved' }, { ...before[1], status: 'saved' }] })
    scored = after // a new scoring
    await screen.click(screen.button(/^Re-score$/))
    await settle()
    const kept = Object.fromEntries(screen.storedJobs().map((j) => [j.jobId, j]))
    expect(kept.a1).toMatchObject({ title: 'After', matchScore: 90, status: 'saved' })
    expect(kept.a2).toMatchObject({ offList: true, status: 'saved' }) // worked on, no longer in the scored list
  })

  const wide = () => Array.from({ length: 300 }, (_, i) => storedJob(`wide${String(i).padStart(3, '0')}`, { title: `Wide ${i}`, matchScore: 50 + (i % 40) }))

  it2('select all reaches every ad of every page, the ones only the server holds too, and Mark rejected is one batched server write that stores nothing in the browser for them', async () => {
    const rows = wide()
    const server = stubList({ route: () => routeAnswer([]), scoredRows: rows, scored: () => ({ meta: {}, jobs: rows }) })
    screen = await mountList({ stored: [] })
    await settle()
    expect(screen.rows().length).toBeLessThan(300) // a page, not the list
    await screen.click(screen.container.querySelector('thead input[type=checkbox]'))
    await settle()
    expect(screen.text()).toContain('300 selected')
    await screen.click(screen.button(/^Mark rejected$/))
    await settle()
    expect(server.batchWrites).toHaveLength(1) // one request, not 300
    expect(server.batchWrites[0].patch).toEqual({ status: 'rejected' })
    expect(new Set(server.batchWrites[0].items.map((item) => item.jobId))).toEqual(new Set(rows.map((r) => r.jobId)))
    expect(server.stateWrites.filter((w) => w.patch.status === 'rejected')).toHaveLength(300)
    expect(Object.values(server.jobState.jobs).every((entry) => entry.status === 'rejected')).toBe(true)
    expect(screen.storedJobs()).toEqual([]) // no browser-list write for a row only the server holds
  })

  it2('Mark saved on a mix of rows: the stored ones follow, the server-only ones are on the server, one request', async () => {
    const rows = wide()
    const server = stubList({ route: () => routeAnswer([]), scoredRows: rows, scored: () => ({ meta: {}, jobs: rows }) })
    screen = await mountList({ stored: [storedJob('wide007', { title: 'Wide 7', matchScore: 57 })] })
    await settle()
    await screen.click(screen.container.querySelector('thead input[type=checkbox]'))
    await settle()
    await screen.click(screen.button(/^Mark saved$/))
    await settle()
    expect(server.batchWrites).toHaveLength(1)
    expect(server.batchWrites[0].items).toHaveLength(300)
    expect(screen.storedJobs().map((j) => [j.jobId, j.status])).toEqual([['wide007', 'saved']]) // still only the row the browser held
  })

  it2('a bulk status the server refuses changes nothing, here or in the browser, and says so', async () => {
    const rows = wide()
    stubList({ route: () => routeAnswer([]), scoredRows: rows, scored: () => ({ meta: {}, jobs: rows }) })
    const served = globalThis.fetch
    vi.stubGlobal('fetch', async (url, options = {}) => (String(url) === '/api/jobs/state/batch'
      ? { ok: false, status: 400, json: async () => ({ error: 'status is not valid' }) }
      : served(url, options)))
    screen = await mountList({ stored: [storedJob('wide007', { title: 'Wide 7', matchScore: 57 })] })
    await settle()
    await screen.click(screen.container.querySelector('thead input[type=checkbox]'))
    await settle()
    await screen.click(screen.button(/^Mark rejected$/))
    await settle()
    expect(screen.storedJobs()[0].status).not.toBe('rejected')
    expect(screen.text()).toContain('The status was not saved: status is not valid')
  })

  it2('a row only this browser has is in the list, and an action on it is saved in the browser', async () => {
    const server = stubList({ route: () => routeAnswer([]) })
    const mine = offList(1)
    screen = await mountList({ stored: [storedJob('s1'), mine] })
    expect(screen.row('Left ad 1')).toBeTruthy()
    const before = screen.storedJobs().find((j) => j.jobId === 'off1')
    await screen.click(screen.row('Left ad 1').querySelector('button[aria-label="Reject"]'))
    await settle()
    expect(screen.storedJobs().find((j) => j.jobId === 'off1').status).toBe('rejected') // saved in this browser, as before
    expect(before.status).toBe('saved')
    expect(server.listCalls.at(-1).extraRows.find((row) => row.jobId === 'off1')).toMatchObject({ status: 'rejected', offList: true })
  })
})
})
