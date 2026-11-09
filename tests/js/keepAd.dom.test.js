// @vitest-environment jsdom
// "Keep this ad" and Mark Applied on rows only the server holds (slice S5e3d), with real clicks.
import fs from 'node:fs'
import path from 'node:path'
import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ago, countWrites, makeApplication, mountScreen, routeAnswer, routeRow, settle, storedJob, stubServer, viewport } from './setup/jobsScreenHarness.js'

vi.setConfig({ testTimeout: 60000, hookTimeout: 60000 })

const ABSENT = routeRow('abs', 'absent', { title: 'The absent ad', copyGroup: 'g', reason: 'why absent' })
const ROUTE = [routeRow('s1'), ABSENT, routeRow('fil', 'filtered', { from: 'filtered', title: 'Filtered Chef' })]
const STORED = [storedJob('s1')]
const ledgerRow = (description = 'THE LEDGER AD TEXT') => (jobId) => ({ jobId, job: { jobId, title: `Ledger ${jobId}`, company: 'Acme', jobUrl: `https://x.example/${jobId}`, description, provider: 'jobspy', status: 'new' }, firstSeen: ago(30), lastSeen: ago(1), closedAt: null, absentSince: null, absentRuns: 0 })
const good = () => routeAnswer(ROUTE)
const NEVER_STORED = ['class', 'reason', 'reasonCode', 'from', 'copyGroup', 'serverOnly']
const PAGE = '../../../src/components/jobs/JobDetailsPage.jsx'
const AI_PANEL_TEXT = 'Analyze Job'

let screen
beforeEach(() => viewport(true))
afterEach(async () => {
  await screen?.unmount()
  screen = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.doUnmock('../../src/components/jobs/JobTailorActions.jsx')
})

const keep = async (where) => { await screen.click(screen.button(/Keep this ad/, where)); await settle() }
const kept = () => screen.storedJobs().find((j) => j.jobId === 'abs')
const absentRow = () => screen.row('The absent ad') ?? screen.row('Ledger abs')

describe('Keep this ad', () => {
  it('from the table: stores the ledger\'s ad, marked, and no display field', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    expect(kept()).toBeUndefined()
    await keep(absentRow())
    const job = kept()
    expect(job.keptByUser).toBe(true)
    expect(job.keptAt).toBeTruthy()
    expect(job.description).toBe('THE LEDGER AD TEXT')
    expect(job.status).toBe('new')
    expect(job.descriptionIncomplete).toBeUndefined()
    for (const field of NEVER_STORED) expect(field in job).toBe(false)
    expect('matchScore' in job).toBe(false)
    expect(screen.raw()).not.toMatch(/"class":|"copyGroup":|"serverOnly":|"reasonCode":/)
  })

  it('the row then works as a stored one: actions on, no Keep button, Save persists', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    expect(absentRow().querySelector('button[aria-label^="Save"]').disabled).toBe(true)
    await keep(absentRow())
    expect(absentRow().querySelector('button[aria-label="Save"]').disabled).toBe(false)
    expect(screen.button(/Keep this ad/, absentRow())).toBeUndefined()
    expect(absentRow().querySelector('input[type=checkbox]').disabled).toBe(false)
    await screen.click(absentRow().querySelector('button[aria-label="Save"]'))
    await settle()
    expect(kept().status).toBe('saved')
  })

  it('from a card', async () => {
    viewport(false)
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/Keep this ad/))
    await settle()
    expect(kept().keptByUser).toBe(true)
  })

  it('from the drawer, and clicking it there does not close or reopen anything', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(absentRow())
    await settle()
    expect(screen.text()).toContain('AI tools, outreach, tailoring and status changes need it saved')
    const drawer = screen.container.querySelector('aside')
    await screen.click(screen.button(/Keep this ad/, drawer))
    await settle()
    expect(kept().keptByUser).toBe(true)
    expect(screen.container.querySelector('aside')?.textContent).not.toContain('AI tools, outreach, tailoring and status changes need it saved')
  })

  it('from Job Details', async () => {
    stubServer({ ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED, file: PAGE, props: { jobId: 'abs' } })
    expect(screen.text()).toContain('THE LEDGER AD TEXT')
    await screen.click(screen.button(/Keep this ad/))
    await settle()
    expect(kept().keptByUser).toBe(true)
    expect(screen.button(/Keep this ad/)).toBeUndefined()
  })

  it('Keep does not open the drawer of the row it is on', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await keep(absentRow())
    expect(screen.container.querySelector('aside')).toBeNull()
  })

  it('a ledger that cannot answer stores nothing and says so, and another try works', async () => {
    let answer = () => null
    stubServer({ route: good, ledger: (jobId) => answer(jobId) })
    screen = await mountScreen({ stored: STORED })
    const raw = screen.raw()
    await keep(absentRow())
    expect(screen.text()).toContain('The ad could not be read from the job history, so nothing was kept')
    expect(screen.raw()).toBe(raw)
    answer = ledgerRow()
    await keep(absentRow())
    expect(kept().keptByUser).toBe(true)
  })

  it('if keeping fails in any other way it says so too', async () => {
    vi.doMock('../../src/modules/jobs/keepAd', async (original) => ({ ...(await original()), keepAd: async () => { throw new Error('odd') } }))
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await keep(absentRow())
    expect(screen.text()).toContain('so nothing was kept')
    vi.doUnmock('../../src/modules/jobs/keepAd')
  })

  it('a record stored meanwhile, say from another tab, keeps its data and gets the mark', async () => {
    stubServer({ health: false })
    screen = await mountScreen({ stored: [storedJob('abs', { status: 'saved', notes: 'mine' })] })
    const { promoteRow } = await import('../../src/modules/jobs/jobsStore.js')
    await act(async () => { promoteRow({ ...ABSENT, serverOnly: true }, { jobId: 'abs', title: 'Ledger', description: 'text' }) })
    expect(kept()).toMatchObject({ status: 'saved', notes: 'mine', keptByUser: true })
    expect(screen.storedJobs()).toHaveLength(1)
  })

  it.each([[''], ['   '], [null]])('a ledger with no ad text (%j): stored, marked incomplete, and it says so', async (description) => {
    stubServer({ route: good, ledger: ledgerRow(description) })
    screen = await mountScreen({ stored: STORED })
    await keep(absentRow())
    expect(kept().descriptionIncomplete).toBe(true)
    await screen.click(absentRow())
    await settle()
    expect(screen.text()).toContain('this copy is incomplete')
  })

  it('a filtered row has no Keep button', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^All$/))
    expect(screen.button(/Keep this ad/, screen.row('Filtered Chef'))).toBeUndefined()
  })
})

describe('a kept row lasts', () => {
  const scored = () => ({ meta: {}, jobs: [storedJob('s1')] })

  async function keepThenReload(server) {
    screen = await mountScreen({ stored: STORED })
    await keep(absentRow())
    await screen.unmount()
    server?.()
    screen = await mountScreen({ keepStorage: true })
  }

  it('through a refresh with no other work on it, in Active', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    await keepThenReload()
    expect(kept().keptByUser).toBe(true)
    expect(absentRow()).toBeTruthy()
    expect(absentRow().querySelector('button[aria-label="Save"]').disabled).toBe(false)
  })

  it('through a re-import that does not hold it: off the list, still kept, still in Active', async () => {
    stubServer({ route: good, ledger: ledgerRow(), scored })
    await keepThenReload()
    expect(kept().offList).toBe(true)
    expect(kept().keptByUser).toBe(true)
    expect(kept().description).toBe('THE LEDGER AD TEXT')
    expect(absentRow()).toBeTruthy()
  })

  it('past the 14 days and under a class Active leaves out', async () => {
    stubServer({ route: good, ledger: ledgerRow(), scored })
    await keepThenReload(() => stubServer({ route: () => routeAnswer([routeRow('s1'), routeRow('abs', 'stale', { title: 'The absent ad', lastSeen: ago(90) })]), scored }))
    expect(absentRow()).toBeTruthy()
    expect(screen.text()).toContain('Stale')
  })

  it('in today\'s list too, when the route fails', async () => {
    stubServer({ route: good, ledger: ledgerRow(), scored })
    await keepThenReload(() => stubServer({ route: () => ({ status: 503, body: { ok: false, message: 'no' } }), scored }))
    expect(screen.text()).toContain('The full list could not be loaded')
    expect(absentRow()).toBeTruthy()
  })

  it('with a status and notes, which persist as on any stored row', async () => {
    stubServer({ route: good, ledger: ledgerRow(), scored })
    screen = await mountScreen({ stored: STORED })
    await keep(absentRow())
    await screen.click(absentRow().querySelector('button[aria-label="Reject"]'))
    await settle()
    const { patchJob } = await import('../../src/modules/jobs/jobsStore.js')
    await act(async () => { patchJob('abs', { notes: 'My note' }) })
    await settle()
    await screen.unmount()
    screen = await mountScreen({ keepStorage: true })
    expect(kept().status).toBe('rejected')
    expect(kept().notes).toBe('My note')
    expect(kept().keptByUser).toBe(true)
  })

  it('a row that disappears and returns keeps its data, the mark included, and outlasts the next absence', async () => {
    const { importJobsFromFile, getDefaultJobsState } = await import('../../src/modules/jobs/jobStorage.js')
    const start = { ...getDefaultJobsState(), jobs: [storedJob('k', { keptByUser: true, keptAt: 'then', outreach: { contacts: [{ name: 'x' }] }, status: 'saved' })] }
    const gone = importJobsFromFile({ jobs: [] }, start)
    expect(gone.jobs[0].offList).toBe(true)
    const back = importJobsFromFile({ jobs: [{ jobId: 'k', title: 'New title', jobUrl: 'https://x.example/k', description: 'Fresh text' }] }, gone)
    expect(back.jobs[0]).toMatchObject({ title: 'New title', description: 'Fresh text', status: 'saved', keptByUser: true, keptAt: 'then', outreach: { contacts: [{ name: 'x' }] } })
    expect(back.jobs[0].offList).toBeUndefined()
    const goneAgain = importJobsFromFile({ jobs: [] }, back)
    expect(goneAgain.jobs).toHaveLength(1)
    expect(goneAgain.jobs[0].keptByUser).toBe(true)
  })

  it('a row with no such mark and no work is still dropped by an import, as ever', async () => {
    const { importJobsFromFile, getDefaultJobsState } = await import('../../src/modules/jobs/jobStorage.js')
    expect(importJobsFromFile({ jobs: [] }, { ...getDefaultJobsState(), jobs: [storedJob('p')] }).jobs).toEqual([])
    const merged = importJobsFromFile({ jobs: [{ jobId: 'p', title: 'x' }] }, { ...getDefaultJobsState(), jobs: [storedJob('p')] })
    expect('keptByUser' in merged.jobs[0]).toBe(false)
  })

  it('a kept row off the list is listed but stays out of the numbers', async () => {
    const { computeJobStats } = await import('../../src/modules/jobs/jobStats.js')
    const { filterJobs, listedJobs } = await import('../../src/modules/jobs/jobFilters.js')
    const jobs = [storedJob('a', { matchScore: 80 }), storedJob('k', { keptByUser: true, offList: true, matchScore: 10 }), storedJob('o', { offList: true, status: 'saved' })]
    expect(listedJobs(jobs).map((j) => j.jobId)).toEqual(['a', 'k'])
    expect(filterJobs(jobs, {}).map((j) => j.jobId)).toEqual(['a', 'k'])
    expect(computeJobStats(jobs)).toEqual(computeJobStats(jobs.filter((j) => !j.offList)))
  })
})

describe('only Keep this ad changes the saved list', () => {
  it('browsing, filtering, selecting, opening and paging leave the payload byte-identical', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    const raw = screen.raw()
    const writes = countWrites(screen.key)
    await screen.click(screen.button(/^All$/))
    await screen.click(screen.box(/Closed \(0\)/))
    await screen.click(screen.box(/Closed \(0\)/))
    await screen.click(screen.box(/Seen in the last 14 days/))
    await screen.click(screen.box(/Seen in the last 14 days/))
    await screen.click([...screen.container.querySelectorAll('th button')].find((b) => /title/i.test(b.textContent)))
    await screen.click(screen.row('T s1').querySelector('input[type=checkbox]'))
    await screen.click(absentRow())
    await settle()
    expect(writes()).toBe(0)
    expect(screen.raw()).toBe(raw)
    await keep(absentRow())
    expect(writes()).toBeGreaterThan(0)
    expect(screen.raw()).not.toBe(raw)
    expect(screen.storedJobs()).toHaveLength(2)
  })

  it('tailoring on a stored row in a composed list writes no display field', async () => {
    viewport(false)
    vi.doMock('../../src/components/jobs/JobTailorActions.jsx', () => ({ default: ({ job, onJobUpdated }) => createElement('button', { type: 'button', onClick: () => onJobUpdated({ ...job, tailoredAssets: { resumeMd: 'x' } }) }, 'Fake tailor') }))
    stubServer({ route: () => routeAnswer([routeRow('s1', 'absent', { copyGroup: 'g' })]), ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/Fake tailor/))
    await settle()
    const [job] = screen.storedJobs()
    expect(job.tailoredAssets).toEqual({ resumeMd: 'x' })
    for (const field of NEVER_STORED) expect(field in job).toBe(false)
  })
})

describe('what needs a stored ad waits for Keep, and says why', () => {
  it('Job Details hides AI tools and contacts until Keep, and then offers them', async () => {
    stubServer({ ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED, file: PAGE, props: { jobId: 'abs' } })
    expect(screen.text()).toContain('AI tools, outreach, tailoring and status changes need it saved: press Keep this ad first')
    expect(screen.text()).not.toContain(AI_PANEL_TEXT)
    expect(screen.text()).not.toMatch(/Related contacts/i)
    await screen.click(screen.button(/Keep this ad/))
    await settle()
    expect(screen.text()).not.toContain('press Keep this ad first')
    expect(screen.text()).toMatch(/Contacts/i)
    expect(screen.text()).toContain(AI_PANEL_TEXT)
  })

  it('the list says why its rows are read-only, and every disabled action says what to do', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    expect(screen.text()).toContain('read-only until you press Keep this ad')
    expect(screen.text()).toContain('bulk actions cover saved rows only')
    const buttons = [...absentRow().querySelectorAll('button[aria-label]')]
    expect(buttons.length).toBeGreaterThan(0)
    // Applied works without Keep (it writes to the tracker, which needs no stored row); every other action waits for Keep.
    const applied = buttons.filter((b) => b.getAttribute('aria-label') === 'Mark as applied')
    expect(applied).toHaveLength(1)
    expect(applied[0].disabled).toBe(false)
    for (const button of buttons.filter((b) => !applied.includes(b))) {
      expect(button.disabled).toBe(true)
      expect(button.title).toBe('Press Keep this ad first')
    }
    expect(absentRow().querySelector('input[type=checkbox]').title).toBe('Press Keep this ad first')
  })

  it('select all covers saved rows only and says so', async () => {
    stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/Select all 1 filtered jobs saved in this browser/))
    expect(screen.text()).toContain('1 selected')
    expect(absentRow().querySelector('input[type=checkbox]').checked).toBe(false)
  })
})

describe('Mark Applied, the same in the drawer and on Job Details', () => {
  async function applyFromDrawer() {
    const server = stubServer({ route: good, ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED })
    await screen.click(absentRow())
    await settle()
    await screen.click(screen.button(/^Mark Applied$/))
    await settle()
    return server
  }
  async function applyFromPage() {
    const server = stubServer({ ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED, file: PAGE, props: { jobId: 'abs' } })
    await screen.click(screen.button(/^Mark as applied$/))
    await settle()
    return server
  }

  it.each([['the drawer', applyFromDrawer], ['Job Details', applyFromPage]])('from %s: an application is posted for the job, and the ad is not stored', async (_, apply) => {
    const raw = () => screen.storedJobs().map((j) => j.jobId)
    const server = await apply()
    expect(server.posts).toHaveLength(1)
    expect(server.posts[0].jobId).toBe('abs')
    expect(raw()).toEqual(['s1'])
    for (const field of NEVER_STORED) expect(field in server.posts[0].posting).toBe(false)
  })

  it('both post the same fields', async () => {
    const drawer = await applyFromDrawer()
    await screen.unmount()
    const page = await applyFromPage()
    expect(Object.keys(drawer.posts[0]).sort()).toEqual(Object.keys(page.posts[0]).sort())
    expect(Object.keys(drawer.posts[0].attempt).sort()).toEqual(Object.keys(page.posts[0].attempt).sort())
    expect(drawer.posts[0].posting.jobId).toBe(page.posts[0].posting.jobId)
    expect(drawer.posts[0].posting.description).toBe('THE LEDGER AD TEXT')
    expect(page.posts[0].posting.description).toBe('THE LEDGER AD TEXT')
  })

  it('the application stays after a refresh and a re-import, with the ad still not stored, and keeps the row in Active', async () => {
    const applications = { a1: makeApplication('a1', 'abs') }
    const answer = () => routeAnswer([routeRow('s1'), routeRow('abs', 'older_key', { title: 'The absent ad', lastSeen: ago(90) })])
    stubServer({ route: answer, ledger: ledgerRow(), applications, scored: () => ({ meta: {}, jobs: [storedJob('s1')] }) })
    screen = await mountScreen({ stored: STORED })
    await settle()
    expect(absentRow()).toBeTruthy()
    expect(kept()).toBeUndefined()
    expect(screen.text()).toContain('applied manually')
    await screen.unmount()
    screen = await mountScreen({ keepStorage: true })
    await settle()
    expect(absentRow()).toBeTruthy()
    expect(kept()).toBeUndefined()
  })
})

describe('Keep this ad is the only write path', () => {
  function sourceFiles(folder) {
    return fs.readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
      const file = path.join(folder, entry.name)
      if (entry.isDirectory()) return sourceFiles(file)
      return /\.jsx?$/.test(entry.name) ? [file] : []
    })
  }
  const callers = (pattern) => sourceFiles('src').filter((file) => pattern.test(fs.readFileSync(file, 'utf-8')))

  it('promoteRow is called only by keepAd, and keepAd only by the button', () => {
    expect(callers(/\bpromoteRow\(/)).toEqual(expect.arrayContaining(['src/modules/jobs/jobsStore.js', 'src/modules/jobs/keepAd.js']))
    expect(callers(/\bpromoteRow\(/)).toHaveLength(2)
    expect(callers(/\bkeepAd\(/).sort()).toEqual(['src/components/jobs/KeepAdButton.jsx', 'src/modules/jobs/keepAd.js'])
  })

  it('addJobIfAbsent has one other caller, for a row the file holds', () => {
    expect(callers(/\baddJobIfAbsent\(/).sort()).toEqual(['src/components/jobs/JobDetailsPage.jsx', 'src/modules/jobs/jobsStore.js'])
    expect(fs.readFileSync('src/components/jobs/JobDetailsPage.jsx', 'utf-8')).toContain('if (found.addable) addJobIfAbsent(found.addable)')
  })

  it('the file rule still holds for a ledger-only row', async () => {
    const { loadJobSources } = await import('../../src/modules/jobs/jobResolve.js')
    const found = await loadJobSources('abs', { jobs: [] }, { autoLoad: async (state) => ({ state: { ...state, jobs: [] }, source: 'scored' }), loadDiscovered: async () => ({ jobs: [] }), loadHistory: async () => ledgerRow()('abs') })
    expect(found.addable).toBeNull()
    expect(found.ledger).toBeTruthy()
  })

  it('opening Job Details of a ledger-only row stores nothing', async () => {
    stubServer({ ledger: ledgerRow() })
    screen = await mountScreen({ stored: STORED, file: PAGE, props: { jobId: 'abs' } })
    expect(screen.storedJobs().map((j) => j.jobId)).toEqual(['s1'])
  })
})
