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
