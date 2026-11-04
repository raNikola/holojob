// @vitest-environment jsdom
// Real clicks on the real Jobs screen (slices S5e3b, S5e3c). The pure rules are in jobTable.test.js and jobListView.test.js.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ago, countWrites, mountScreen, routeAnswer, routeRow, settle, storedJob, stubServer, viewport } from './setup/jobsScreenHarness.js'

const STORED = [storedJob('s1', { status: 'saved', matchScore: 80, matchLabel: 'Strong', outreach: { contacts: [{ name: 'x' }] } }), storedJob('s2')]
const ROUTE = [
  routeRow('s1'), routeRow('s2'), routeRow('abs', 'absent'), routeRow('old', 'absent', { lastSeen: ago(30) }), routeRow('key', 'older_key'), routeRow('cl', 'closed'),
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

const many = (count) => Array.from({ length: count }, (_, i) => storedJob(`j${String(i).padStart(4, '0')}`, { title: `Job ${i}`, matchScore: i % 100 }))

describe('the table on a long list', () => {
  it('sorts the whole list, then shows a batch', async () => {
    stubServer({ health: false })
    const jobs = many(350)
    jobs[349] = { ...jobs[349], matchScore: 100, title: 'The best ad' }
    screen = await mountScreen({ stored: jobs })
    expect(screen.rows()).toHaveLength(100)
    expect(screen.rows()[0].textContent).toContain('The best ad')
    expect(screen.text()).toContain('Showing 100 of 350')
    await screen.click(screen.button(/Show 100 more/))
    expect(screen.rows()).toHaveLength(200)
  })

  it('selection survives Show more and a re-sort, and neither writes storage', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(350) })
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

  it('select all covers every filtered row, says what is off screen, and clears', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(350) })
    const writes = countWrites(screen.key)
    await screen.click(screen.button(/Select all 350 filtered/))
    expect(screen.text()).toContain('350 selected')
    expect(screen.text()).toContain('250 selected jobs are not shown yet')
    await screen.click(screen.button(/Clear selection of all 350/))
    expect(screen.text()).not.toContain('selected jobs are')
    expect(writes()).toBe(0)
  })

  it('a filter change resets the selection and the batch, keeps its persistence, and the stored jobs stay byte-identical', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(150) })
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

  it('a row\'s new status keeps the rows loaded', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(250) })
    await screen.click(screen.button(/Show 100 more/))
    await screen.click(screen.rows()[150].querySelector('button[aria-label="Save"]'))
    expect(screen.rows()).toHaveLength(200)
    expect(screen.storedJobs().filter((j) => j.status === 'saved')).toHaveLength(1)
  })

  it('bulk status acts on the selected stored rows', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(3) })
    await screen.click(screen.rows()[0].querySelector('input[type=checkbox]'))
    await screen.click(screen.button(/^Mark saved$/))
    await settle()
    expect(screen.storedJobs().filter((j) => j.status === 'saved')).toHaveLength(1)
  })

  it('the keyboard keeps its place when the last Show more button goes', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(150) })
    const button = screen.button(/Show 50 more/)
    button.focus()
    await screen.click(button)
    expect(document.activeElement?.getAttribute('role')).toBe('status')
  })

  it('the Score column is judged on the whole list, also after a re-sort moves the only score out of the batch', async () => {
    stubServer({ health: false })
    const jobs = many(150).map((j, i) => ({ ...j, matchScore: i === 0 ? 5 : undefined, title: i === 0 ? 'ZZZ last by title' : j.title }))
    screen = await mountScreen({ stored: jobs })
    await screen.click([...screen.container.querySelectorAll('th button')].find((b) => /title/i.test(b.textContent)))
    expect(screen.text()).not.toContain('ZZZ last by title')
    expect([...screen.container.querySelectorAll('th button')].some((b) => /score/i.test(b.textContent))).toBe(true)
  })

  it('a narrow window mounts cards only', async () => {
    viewport(false)
    stubServer({ health: false })
    screen = await mountScreen({ stored: many(3) })
    expect(screen.container.querySelector('table')).toBeNull()
    expect(screen.text()).toContain('Job 1')
  })
})

describe('Active and All', () => {
  it('Active is the default, with badges, reasons and Not scored', async () => {
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    expect(screen.button(/^Active$/).getAttribute('aria-pressed')).toBe('true')
    expect(screen.rows()).toHaveLength(3)
    expect(screen.text()).toContain('of 3 jobs shown')
    expect(screen.text()).toContain('Not in latest search')
    expect(screen.text()).toContain('why absent')
    expect(screen.text()).toContain('Not scored')
  })

  it('the toggle, the class filter and the 14-day filter change the list and write nothing', async () => {
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
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

  it('a change of mode or class resets the selection', async () => {
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.row('T s2').querySelector('input[type=checkbox]'))
    expect(screen.text()).toContain('1 selected')
    await screen.click(screen.button(/^All$/))
    expect(screen.text()).not.toContain('1 selected')
  })

  it('the old filter is off and disabled in a composed list, and works on today\'s list', async () => {
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/More filters/) ?? screen.container)
    expect(screen.box(/Show jobs absent/)?.disabled).toBe(true)
    await screen.unmount()
    stubServer({ health: false })
    screen = await mountScreen({ stored: [...STORED, storedJob('off', { offList: true, status: 'saved' })] })
    expect(screen.rows()).toHaveLength(2)
    await screen.click(screen.button(/More filters/) ?? screen.container)
    expect(screen.box(/Show jobs absent/)?.disabled).toBe(false)
    await screen.click(screen.box(/Show jobs absent/))
    expect(screen.rows()).toHaveLength(3)
  })

  it('the Analytics numbers are the same with the route on and off', async () => {
    const scored = () => ({ meta: {}, jobs: STORED })
    stubServer({ route: good, scored })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^Analytics$/))
    await settle()
    const on = screen.text()
    await screen.unmount()
    stubServer({ route: failed, scored })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^Analytics$/))
    await settle()
    expect(screen.text()).toBe(on)
  })
})

describe('a Stale ad', () => {
  const STALE = routeRow('old1', 'stale', { title: 'A stale ad', reason: 'No sighting for 40 days and 3 successful runs of this search. Last seen 2026-09-25' })
  const stale = () => routeAnswer([routeRow('s1'), STALE])

  it('is out of Active, in All with its badge and counts, and under the Stale filter', async () => {
    stubServer({ route: stale })
    screen = await mountScreen({ stored: [storedJob('s1')] })
    expect(screen.row('A stale ad')).toBeUndefined()
    await screen.click(screen.button(/^All$/))
    expect(screen.row('A stale ad').textContent).toContain('Stale')
    expect(screen.row('A stale ad').textContent).toContain('No sighting for 40 days and 3 successful runs')
    await screen.click(screen.box(/Stale \(1\)/))
    expect(screen.rows()).toHaveLength(1)
  })

  it('stays in Active with work on it', async () => {
    stubServer({ route: stale })
    screen = await mountScreen({ stored: [storedJob('s1'), storedJob('old1', { status: 'saved', offList: true })] })
    expect(screen.row('A stale ad').textContent).toContain('Stale')
    expect(screen.row('A stale ad').querySelector('button[aria-label="Reject"]').disabled).toBe(false)
  })
})

describe('when the route does not give a whole list', () => {
  it('a 503 keeps the local list, says so and offers another try', async () => {
    const server = stubServer({ route: failed })
    screen = await mountScreen({ stored: STORED })
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
    stubServer({ route: () => routeAnswer([routeRow('s1')], 'missing') })
    screen = await mountScreen({ stored: STORED })
    expect(screen.text()).not.toContain('This list is incomplete')
    await screen.click(screen.button(/^All$/))
    expect(screen.text()).toContain('This list is incomplete: filtered ads could not be read')
  })

  it('an empty answer never clears stored rows', async () => {
    stubServer({ route: () => routeAnswer([]) })
    screen = await mountScreen({ stored: STORED })
    expect(screen.rows()).toHaveLength(2)
    expect(screen.storedJobs()).toHaveLength(2)
  })

  it('no API: today\'s list, no toggle, and the route is never asked', async () => {
    const server = stubServer({ health: false })
    screen = await mountScreen({ stored: STORED })
    expect(screen.button(/^All$/)).toBeUndefined()
    expect(server.allCalls).toBe(0)
    expect(screen.rows()).toHaveLength(2)
  })

  it('a failed application store is flagged, and copies stay apart', async () => {
    stubServer({ route: () => routeAnswer([routeRow('a', 'absent', { copyGroup: 'g' }), routeRow('b', 'absent', { copyGroup: 'g' })]) })
    const real = globalThis.fetch
    vi.stubGlobal('fetch', async (url, options) => (String(url).startsWith('/api/applications') ? { ok: false, status: 500, json: async () => ({ error: 'no' }) } : real(url, options)))
    screen = await mountScreen({ stored: [] })
    await settle()
    expect(screen.rows()).toHaveLength(2)
    expect(screen.text()).toContain('Your applications could not be loaded')
  })
})

describe('asking the route again', () => {
  it('after Re-score', async () => {
    const server = stubServer({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountScreen({ stored: STORED })
    const before = server.allCalls
    await screen.click(screen.button(/^Re-score$/))
    await settle()
    expect(server.allCalls).toBeGreaterThan(before)
  })

  it.each(['done', 'failed'])('after a Re-scrape that ended %s', async (status) => {
    let finished
    vi.doMock('../../src/modules/jobs/useRescrapeRun', () => ({ useRescrapeRun: ({ onFinished }) => { finished = onFinished; return { start() {}, view: { active: false } } } }))
    const server = stubServer({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountScreen({ stored: STORED })
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
    const server = stubServer({ route: good, scored: () => ({ meta: {}, jobs: [{ jobId: 'from-file', title: 'From file' }] }) })
    screen = await mountScreen({ stored: STORED })
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
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    const row = screen.row('Filtered Chef')
    expect(row.querySelector('input[type=checkbox]')).toBeNull()
    expect(row.querySelector('a[href="https://x.example/fil"]')).not.toBeNull()
    await screen.click(row)
    expect(screen.text()).not.toContain('Open full details')
  })

  it('a filtered card opens nothing either', async () => {
    viewport(false)
    stubServer({ route: () => routeAnswer([routeRow('fil', 'filtered', { from: 'filtered', title: 'Filtered Chef' })]) })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    const card = [...screen.container.querySelectorAll('div.rounded-xl')].find((d) => d.textContent.includes('Filtered Chef') && d.textContent.includes('Open ad'))
    await screen.click(card)
    expect(screen.text()).not.toContain('Open full details')
  })

  it('Add job opens the form prefilled and saves nothing', async () => {
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
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
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    await screen.click(screen.button(/^Add job$/, screen.row('Filtered Chef')))
    await screen.click(screen.button(/^Cancel$/))
    await screen.click(screen.button(/^Add job$/))
    expect([...screen.container.querySelectorAll('input')].map((i) => i.value)).not.toContain('Filtered Chef')
  })

  it('opening the drawer of a server-only row stores nothing, and its ad text comes from the ledger', async () => {
    stubServer({ route: good, ledger: (jobId) => ({ jobId, job: { jobId, title: 'T abs', description: 'THE LEDGER AD TEXT' }, firstSeen: ago(30), lastSeen: ago(1), closedAt: null }) })
    screen = await mountScreen({ stored: STORED })
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
