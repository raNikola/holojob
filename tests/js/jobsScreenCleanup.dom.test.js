// @vitest-environment jsdom
// Jobs screen cleanup (2026-11-19): one compact filter bar, run buttons in order with an inline Running state, end-of-run toasts,
// the Activity tab, and the inline URL import gone from the controls row. Pure rules: rescrapeProgress.dom.test.js, jobTable.test.js.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { mountScreen, routeAnswer, routeRow, settle, storedJob, stubServer, viewport } from './setup/jobsScreenHarness.js'

const STORED = [storedJob('s1', { matchScore: 80, matchLabel: 'Strong' }), storedJob('s2')]
const good = () => routeAnswer([routeRow('s1'), routeRow('s2')])

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

const idleView = { active: false, run: null, events: [], cancelRequested: false, incompleteCommit: null, scoringBehind: false }

function mockRescrape(view, capture = {}) {
  vi.doMock('../../src/modules/jobs/useRescrapeRun', () => ({
    useRescrapeRun: ({ onFinished }) => { capture.finished = onFinished; return { start() {}, refresh() {}, view } },
  }))
}

describe('the controls row', () => {
  it('orders Re-scrape jobs, Re-score, then the Skip LinkedIn checkbox, and has no inline URL import', async () => {
    mockRescrape(idleView)
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    const scrape = screen.button(/^Re-scrape jobs$/)
    const score = screen.button(/^Re-score$/)
    const skip = screen.box(/Skip LinkedIn this time/)
    expect(scrape && score && skip).toBeTruthy()
    const before = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
    expect(before(scrape, score)).toBe(true)
    expect(before(score, skip)).toBe(true)
    expect(screen.container.querySelector('input[placeholder="Paste job URL…"]')).toBeNull()
    expect(screen.button(/Import URL/)).toBeUndefined()
  })

  it('shows Running… with the current source while a Re-scrape is going, and no Details link or event list', async () => {
    mockRescrape({
      ...idleView, active: true, run: { runId: 'r1', status: 'running', orchestrator: 'rescrape' },
      events: [{ type: 'run_start' }, { type: 'source_start', source: 'jobspy' }],
    })
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    expect(screen.button(/^Running… jobspy$/)).toBeTruthy()
    expect(screen.button(/^Details$/)).toBeUndefined()
    expect(screen.container.querySelector('details')).toBeNull()
  })
})

describe('end of a run', () => {
  it('a failed Re-scrape is a persistent error toast, not only an Activity entry', async () => {
    const capture = {}
    mockRescrape(idleView, capture)
    stubServer({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountScreen({ stored: STORED })
    await act(async () => { await capture.finished({ status: 'failed' }) })
    await settle()
    const alert = screen.container.querySelector('[data-testid="toast-stack"] [role="alert"]')
    expect(alert?.textContent).toContain('Re-scrape failed')
    expect(alert.querySelector('button[aria-label="Dismiss"]')).toBeTruthy()
  })

  it('a finished Re-scrape is a status toast', async () => {
    const capture = {}
    mockRescrape(idleView, capture)
    stubServer({ route: good, scored: () => ({ meta: {}, jobs: STORED }) })
    screen = await mountScreen({ stored: STORED })
    await act(async () => { await capture.finished({ status: 'ok' }) })
    await settle()
    expect(screen.container.querySelector('[data-testid="toast-stack"] [role="status"]')?.textContent).toContain('Re-scrape done: 2 jobs')
  })
})

describe('the filter bar and the count row', () => {
  it('has no Filters heading, keeps the info icons, and holds More filters and Clear all in the bar', async () => {
    mockRescrape(idleView)
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    expect([...screen.container.querySelectorAll('h3')].some((h) => h.textContent === 'Filters')).toBe(false)
    expect(screen.container.querySelector('#filter-search').getAttribute('aria-label')).toBe('Search')
    expect(screen.container.querySelector('button[aria-label="About Search"]')).toBeTruthy()
    expect(screen.container.querySelector('button[aria-label="About Status"]')).toBeTruthy()
    const bar = screen.container.querySelector('#filter-search').closest('.rounded-xl')
    expect(screen.button(/More filters/, bar)).toBeTruthy()
    expect(screen.button(/^Clear all$/, bar)).toBeTruthy()
  })
})

describe('the Activity tab', () => {
  it('opens after Analytics, holds the latest Re-scrape event log and the run history, and the Jobs tab no longer has them', async () => {
    mockRescrape({ ...idleView, run: { runId: 'r1', status: 'ok', orchestrator: 'rescrape' }, events: [{ type: 'run_end', status: 'ok' }] })
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    const tabs = [...screen.container.querySelectorAll('[role="tab"], button')].map((b) => b.textContent)
    expect(tabs.indexOf('Activity')).toBe(tabs.indexOf('Analytics') + 1)
    expect(screen.text()).not.toContain('Run finished')
    await screen.click(screen.button(/^Activity$/))
    await settle()
    expect(screen.text()).toContain('Latest Re-scrape')
    expect(screen.text()).toContain('Run finished: ok')
    expect(screen.text()).toContain('What each run read, kept and saved')
  })
})

describe('the Pipeline tab keeps the URL import', () => {
  it('Import job by URL is offered there', async () => {
    mockRescrape(idleView)
    stubServer({ route: good })
    screen = await mountScreen({ stored: STORED })
    await screen.click(screen.button(/^Pipeline$/))
    await settle()
    expect(screen.text()).toContain('Import job by URL')
  })
})
