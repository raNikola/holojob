// @vitest-environment jsdom
// The screens other than the Jobs list, when the browser holds only the ads the owner worked on and the server holds the whole list
// (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P4 S5): the Dashboard's numbers, the AI context, Job Details, and the Outreach job picker.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startListServer } from './setup/jobsListServer.js'
import { countWrites, mountScreen, routeAnswer, routeRow, settle, storedJob, stubServer, viewport } from './setup/jobsScreenHarness.js'
import { loadJobSourcesFromServer } from '../../src/modules/jobs/jobResolve.js'
import { fetchServerAd } from '../../src/modules/jobs/jobListClient.js'

vi.setConfig({ testTimeout: 60000, hookTimeout: 60000 })
const DASHBOARD = '../../../src/components/dashboard/DashboardHome.jsx'
const PAGE = '../../../src/components/jobs/JobDetailsPage.jsx'

let screen
beforeEach(() => viewport(true))
afterEach(async () => {
  await screen?.unmount()
  screen = null
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const scoredRow = (n, extra = {}) => ({ jobId: `r${String(n).padStart(2, '0')}`, title: `Server ad ${n}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/r${n}`, provider: 'jobspy', description: `The text of server ad ${n}`, llmFacts: { _fingerprint: `f${n}` }, matchScore: 30 + n, matchLabel: 'Good', priority: 'P2', applyRecommendation: 'Maybe', blockedBy: [], dataStatus: 'ok', ...extra })
const SERVER_ROWS = Array.from({ length: 30 }, (_, n) => scoredRow(n))

describe('the Dashboard', () => {
  const cardText = () => screen.text()

  it('shows the numbers of the whole list from the server when the browser holds only the ads the owner worked on', async () => {
    stubServer({ listServer: true, scoredRows: SERVER_ROWS, route: () => routeAnswer([]) })
    screen = await mountScreen({ file: DASHBOARD, props: { onNavigate() {} }, server: true, stored: [storedJob('r01', { status: 'saved', matchScore: 31 })] })
    await settle()
    expect(cardText()).toMatch(/Jobs discovered\s*30/)
  })

  it('without the server\'s list it works out the numbers from the browser\'s own rows, as ever', async () => {
    stubServer({ listServer: true, scoredRows: SERVER_ROWS, route: () => routeAnswer([]) })
    screen = await mountScreen({ file: DASHBOARD, props: { onNavigate() {} }, server: false, stored: [storedJob('r01', { status: 'saved', matchScore: 31 })] })
    await settle()
    expect(cardText()).toMatch(/Jobs discovered\s*1/)
  })

  it('writes nothing to the browser\'s list', async () => {
    stubServer({ listServer: true, scoredRows: SERVER_ROWS, route: () => routeAnswer([]) })
    screen = await mountScreen({ file: DASHBOARD, props: { onNavigate() {} }, server: true, stored: [storedJob('r01', { status: 'saved' })] })
    const writes = countWrites(screen.key)
    await settle()
    expect(writes()).toBe(0)
    expect(screen.storedJobs().map((j) => j.jobId)).toEqual(['r01'])
  })
})

describe('Job Details when the server holds the list', () => {
  it('opens an ad the browser does not hold, from the server, read-only, and stores nothing', async () => {
    stubServer({ listServer: true, scoredRows: SERVER_ROWS, route: () => routeAnswer([routeRow('r05')]) })
    screen = await mountScreen({ file: PAGE, props: { jobId: 'r05' }, server: true, stored: [] })
    const before = screen.raw()
    await settle()
    expect(screen.text()).toContain('Server ad 5')
    expect(screen.text()).toContain('The text of server ad 5')
    expect(screen.button(/Keep this ad/)).toBeTruthy() // read-only until Keep
    expect(screen.raw()).toBe(before)
    expect(screen.storedJobs()).toEqual([])
  })

  it('an ad the browser holds opens from the browser\'s own row, whatever the server says', async () => {
    stubServer({ listServer: true, scoredRows: SERVER_ROWS, route: () => routeAnswer([]) })
    screen = await mountScreen({ file: PAGE, props: { jobId: 'r07' }, server: true, stored: [storedJob('r07', { title: 'My own copy', status: 'saved', description: 'My own text' })] })
    await settle()
    expect(screen.text()).toContain('My own copy')
    expect(screen.button(/Keep this ad/)).toBeUndefined() // a stored row: nothing to keep
  })
})

describe('the sources of Job Details, from the server', () => {
  let server
  beforeEach(async () => { server = await startListServer({ pageSize: 4 }) })
  afterEach(() => server.close())
  const load = (jobId, state, extra = {}) => loadJobSourcesFromServer(jobId, state, { fetchAd: (id) => fetchServerAd(id, server.fetchFn), loadHistory: async () => ({ ledger: true }), ...extra })

  it('an ad the server holds comes with its text and facts, is never `addable`, and needs no ledger', async () => {
    const found = await load('j02', { jobs: [] })
    expect(found).toMatchObject({ fileChecked: true, inFile: true, addable: null, ledger: null })
    expect(found.fileJob.description).toContain('The long ad text number 2')
    expect(found.fileJob.llmFacts).toBeTruthy()
    expect(found.row).toBe(found.fileJob)
  })

  it('an ad the server holds no scored row for goes to the ledger, and an off-list stored ad is not in the latest run', async () => {
    const found = await load('ledger-only-1', { jobs: [{ jobId: 'ledger-only-1', offList: true, status: 'saved', description: 'kept text' }] })
    expect(found).toMatchObject({ inFile: false, fileJob: null, row: null, addable: null, ledger: { ledger: true } })
  })

  it('with no API it asks nothing of the server and says the file was not checked', async () => {
    let asked = 0
    const found = await load('j02', { jobs: [] }, { apiAvailable: false, fetchAd: async () => { asked += 1 } })
    expect(asked).toBe(0)
    expect(found).toMatchObject({ fileChecked: false, inFile: false, addable: null })
  })
})
