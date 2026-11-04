// @vitest-environment jsdom
// The live view and Cancel on the Activity screen (S7c), driven in jsdom with fake timers and a stateful stub of the server.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ActivityScreen from '../../src/components/activity/ActivityScreen.jsx'
import { project } from '../../scripts/run-history.js'
import { ev, fakeServer, importBlock, liveBody, record, running } from './setup/activityFixtures.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root
let container
const tick = (ms = 0) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
function visibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  return act(async () => { document.dispatchEvent(new window.Event('visibilitychange')) })
}

/** The server, as a world that changes: the run's record, whether a cancel is on file, the events so far. */
function world(extra = {}) {
  const w = { rec: running(9), flag: false, events: [], alive: true, ...extra }
  w.finish = (changes) => { w.rec = { ...w.rec, finishedAt: '2026-11-01T09:20:00+00:00', ...changes } }
  w.server = (overrides = {}) => fakeServer({
    list: () => ({ status: 200, body: { ok: true, runs: [project(w.rec, { alive: w.alive, cancelRequested: w.flag }), project(record(8))], next: null, skipped: 0, retentionDays: 90, activeRunId: null } }),
    live: (url) => {
      const after = Number(/after=(\d+)/.exec(url)[1])
      return { status: 200, body: liveBody(w.rec, { events: w.events.slice(after), next: w.events.length, alive: w.alive, cancelRequested: w.flag }) }
    },
    cancel: () => { w.flag = true; return { status: 202, body: { ok: true, result: 'cancel_requested', message: 'Cancel requested.' } } },
    ...overrides,
  })
  return w
}

async function mount(fetchFn) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(ActivityScreen, { fetchFn })) })
  await tick(0)
  const find = (pattern, within = container) => [...within.querySelectorAll('button')].find((b) => pattern.test(b.textContent))
  return {
    text: () => container.textContent,
    panel: () => container.querySelector('[data-testid=live-run]'),
    cards: () => [...container.querySelectorAll('[data-testid=run-row]')],
    button: find,
    click: async (element) => { await act(async () => { element.click() }); await tick(0) },
  }
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
  vi.setSystemTime(new Date('2026-11-01T09:02:10+00:00'))
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  root = null
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('the run in progress', () => {
  it('shows where it is, its sources as they report, its events and how long it has run', async () => {
    const w = world({ events: [ev('run_start'), ev('step_start', { step: 'discovery' }), ev('source_start', { source: 'jobspy' })] })
    const server = w.server()
    const screen = await mount(server)
    const text = screen.panel().textContent
    expect(text).toContain('A run is in progress')
    expect(text).toContain('Running')
    expect(text).toContain('Reading the sources')
    expect(text).toContain('Running for 2 min 10 s (as of the last update)')
    expect(screen.panel().querySelector('table[aria-label="Sources so far"]').textContent).toMatch(/jobspy\s*Reading…/)
    expect(text).toContain('Reading jobspy') // the latest event, in the collapsed list
    expect(text).toContain('(3 events)')

    w.events.push(ev('source_end', { source: 'jobspy', status: 'ok', read: 120, kept: 40 }), ev('source_start', { source: 'infostud' }))
    await tick(3000)
    const table = screen.panel().querySelector('table[aria-label="Sources so far"]').textContent
    expect(table).toMatch(/jobspy\s*OK\s*120\s*40/)
    expect(table).toMatch(/infostud\s*Reading…/)
    expect(screen.panel().textContent).toContain('(5 events)')
    expect(server.count(/GET \/api\/runs\/run0009\?after=3$/)).toBe(1)
  })

  it('has a collapsible list of every event, in the words the Jobs screen uses', async () => {
    const w = world({ events: [ev('run_start'), ev('step_start', { step: 'discovery' }), ev('source_start', { source: 'jobspy' })] })
    const screen = await mount(w.server())
    const details = screen.panel().querySelector('details')
    expect(details.open).toBe(false)
    expect([...details.querySelectorAll('li')].map((li) => li.textContent.replace(/^[\d:,\sAPM]+/, ''))).toEqual(['Run started', 'Discovery started', 'Reading jobspy'])
  })

  it('asks nothing live when nothing is running, and the list only once', async () => {
    const server = fakeServer({ list: () => ({ status: 200, body: { ok: true, runs: [project(record(8))], next: null, retentionDays: 90 } }) })
    const screen = await mount(server)
    expect(screen.panel()).toBeNull()
    await tick(10 * 60 * 1000)
    expect(server.calls.map((c) => c.url)).toEqual(['/api/runs?limit=30'])
  })

  it('a hidden tab polls nothing, and the list does not ask again', async () => {
    const w = world()
    const server = w.server()
    await mount(server)
    expect(server.count(/runs\/run0009/)).toBe(1)
    await visibility('hidden')
    await tick(5 * 60 * 1000)
    expect(server.count(/runs\/run0009/)).toBe(1)
    expect(server.count(/GET \/api\/runs\?/)).toBe(1)
    await visibility('visible')
    expect(server.count(/runs\/run0009/)).toBe(2)
  })

  it('says it is retrying when the live view cannot be reached, and the run is not blamed', async () => {
    const w = world()
    let down = false
    const server = w.server({ live: () => (down ? new Error('offline') : { status: 200, body: liveBody(w.rec) }) })
    const screen = await mount(server)
    down = true
    await tick(3000)
    expect(screen.panel().textContent).toContain('The live view could not be updated (The server could not be reached.). Trying again in 3 s. The run itself is not affected.')
    await tick(3000)
    expect(screen.panel().textContent).toContain('Trying again in 6 s')
  })

  it('stores nothing in the browser', async () => {
    const write = vi.spyOn(Storage.prototype, 'setItem')
    const w = world()
    const screen = await mount(w.server())
    await screen.click(screen.button(/Cancel run/))
    await screen.click(screen.button(/Yes, cancel/))
    expect(write).not.toHaveBeenCalled()
    expect(localStorage.length + sessionStorage.length).toBe(0)
  })
})

describe('Cancel is offered only where it can work', () => {
  it('for a Re-scrape that is going', async () => {
    const screen = await mount(world().server())
    expect(screen.button(/^Cancel run$/)).toBeDefined()
  })

  it('not for a run that was not started by a Re-scrape', async () => {
    const screen = await mount(world({ rec: running(9, { orchestrator: undefined }) }).server())
    expect(screen.button(/Cancel run/)).toBeUndefined()
    expect(screen.panel().textContent).toContain('was not started by a Re-scrape, so it cannot be cancelled here')
  })

  it('not for a run that has finished, and not when a cancel is already on file', async () => {
    const finished = await mount(fakeServer({ list: () => ({ status: 200, body: { ok: true, runs: [project(record(8))], next: null, retentionDays: 90 } }) }))
    expect(finished.button(/Cancel run/)).toBeUndefined()
    await act(async () => root.unmount())
    container.remove()
    const asked = await mount(world({ flag: true }).server())
    expect(asked.button(/Cancel run/)).toBeUndefined()
    expect(asked.panel().textContent).toContain('Cancel requested. The run stops at its next safe point.')
  })
})

describe('cancelling', () => {
  it('asks first, and "Keep running" sends nothing', async () => {
    const server = world().server()
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    expect(screen.text()).toContain('Cancel this run? The ads it has already collected are saved and nothing else changes. Scoring is skipped.')
    await screen.click(screen.button(/Keep running/))
    expect(screen.button(/^Cancel run$/)).toBeDefined()
    expect(server.count(/POST/)).toBe(0)
  })

  it('sends one request with the run id, then says only that a cancel was requested', async () => {
    const w = world()
    const server = w.server()
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    const post = server.calls.find((c) => c.method === 'POST')
    expect(post.url).toBe('/api/rescrape/cancel')
    expect(JSON.parse(post.body)).toEqual({ runId: 'run0009' })
    expect(post.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(server.count(/POST/)).toBe(1)
    const panel = screen.panel().textContent
    expect(panel).toContain('Cancel requested. The run stops at its next safe point.')
    expect(screen.button(/Cancel run/)).toBeUndefined()
  })

  it('"Cancel requested" is not "Cancelled": until the record says so, the run is still shown as running and nothing claims it stopped', async () => {
    const w = world({ events: [ev('run_start'), ev('source_start', { source: 'jobspy' })] })
    const screen = await mount(w.server())
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    for (let i = 0; i < 3; i += 1) {
      await tick(3000) // the polls that follow: the record still says running, and the server now reports the request
      const text = screen.text()
      expect(screen.panel().textContent).toContain('A run is in progress')
      expect(screen.panel().textContent).toContain('Running')
      expect(screen.panel().textContent).toContain('Cancel requested. The run stops at its next safe point.')
      expect(text).not.toMatch(/was cancelled|Cancelled|has stopped|stopped\./)
      expect(text).not.toContain('collected ads were saved') // no outcome is claimed before the record has one
      expect(screen.cards().some((card) => /Cancelled/.test(card.textContent))).toBe(false)
    }
    expect(screen.text().match(/Cancel requested\. The run stops at its next safe point\./g)).toHaveLength(1)
  })

  it('when the record says cancelled, the S6 outcome is said, the list is read once more and the live view stops', async () => {
    const w = world({ events: [ev('run_start')] })
    const server = w.server()
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    w.finish({ status: 'cancelled', steps: [{ name: 'discovery', status: 'cancelled', exitCode: 76 }], cancel: { requestedAt: '2026-11-01T09:02:00+00:00', outcome: 'collected_ads_saved', saved: 4 },
      import: importBlock({ kind: 'partial', complete: false, saved: 4, new: 2, refreshed: 2, ledger: undefined }) })
    const listsBefore = server.count(/GET \/api\/runs\?/)
    await tick(3000)
    expect(server.count(/GET \/api\/runs\?/)).toBe(listsBefore + 1)
    expect(screen.panel()).toBeNull()
    const sentence = 'The last run was cancelled. 4 collected ads were saved. Nothing else changed. Scoring was skipped.'
    expect(screen.cards()[0].textContent).toContain(sentence)
    expect(screen.cards()[0].textContent).toContain('Cancelled')
    expect(screen.text().split(sentence)).toHaveLength(2) // said once: by the run's card, not repeated in a notice
    const liveCalls = server.count(/runs\/run0009/)
    await tick(10 * 60 * 1000)
    expect(server.count(/runs\/run0009/)).toBe(liveCalls)
    expect(server.count(/GET \/api\/runs\?/)).toBe(listsBefore + 1)
  })

  it('says it when the step had to be stopped hard, and when the cancel came after the jobs were saved', async () => {
    const hard = world()
    const screen = await mount(hard.server())
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    hard.finish({ status: 'cancelled', steps: [{ name: 'discovery', status: 'cancelled', exitCode: -9 }], cancel: { requestedAt: null, outcome: 'stopped_nothing_imported' } })
    await tick(3000)
    expect(screen.cards()[0].textContent).toContain('The last run was cancelled. No ads were saved. Nothing else changed. Scoring was skipped.')
    await act(async () => root.unmount())
    container.remove()

    const late = world()
    const second = await mount(late.server())
    await second.click(second.button(/^Cancel run$/))
    await second.click(second.button(/Yes, cancel the run/))
    late.finish({ status: 'ok', steps: [{ name: 'discovery', status: 'ok', exitCode: 0 }], cancel: { requestedAt: null, outcome: 'imported_before_cancel' } })
    await tick(3000)
    expect(second.cards()[0].textContent).toContain('The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped.')
    expect(second.text().split('The cancel came after the jobs were saved').length).toBe(2)
    expect(second.cards()[0].textContent).toContain('OK')
    expect(second.cards()[0].textContent).not.toMatch(/The last run was cancelled/)
  })

  it('a double click sends one request', async () => {
    const w = world()
    let release
    const server = w.server({ cancel: () => new Promise((resolve) => { release = () => { w.flag = true; resolve({ status: 202, body: { ok: true, result: 'cancel_requested' } }) } }) })
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    const yes = screen.button(/Yes, cancel the run/)
    await act(async () => { yes.click(); yes.click(); yes.click() })
    expect(server.count(/POST/)).toBe(1)
    expect(screen.text()).toContain('Sending…')
    await act(async () => { release() })
    expect(server.count(/POST/)).toBe(1)
    expect(screen.panel().textContent).toContain('Cancel requested.')
  })

  it.each([
    ['already requested', { status: 200, body: { ok: true, result: 'cancel_already_requested', message: 'A cancel was already requested for this run.' } }, 'requested'],
    ['already cancelled', { status: 200, body: { ok: true, result: 'already_cancelled', message: 'This run was already cancelled. Nothing changed.' } }, 'settled'],
    ['already finished', { status: 200, body: { ok: true, result: 'already_finished', message: 'This run has already finished. Nothing changed.' } }, 'settled'],
    ['no longer running', { status: 200, body: { ok: true, result: 'not_running', message: 'This run is no longer running (it stopped without finishing). Nothing changed.' } }, 'settled'],
    ['not a Re-scrape', { status: 409, body: { ok: false, result: 'not_cancellable', message: 'Only a Re-scrape can be cancelled. Nothing changed.' } }, 'refused'],
    ['unknown run', { status: 404, body: { ok: false, result: 'unknown_run', message: 'There is no such run.' } }, 'refused'],
    ['bad id', { status: 422, body: { ok: false, error: 'invalid', message: 'The run id is not valid.' } }, 'refused'],
  ])('renders the answer "%s"', async (_name, reply, kind) => {
    const w = world()
    const screen = await mount(w.server({ cancel: () => reply }))
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    if (kind === 'requested') {
      expect(screen.panel().textContent).toContain('Cancel requested. The run stops at its next safe point.')
      return
    }
    expect(screen.text()).toContain(reply.body.message)
    expect(screen.text()).not.toContain('Cancel requested. The run stops')
    expect(screen.button(/^Cancel run$/)).toBeDefined() // nothing was requested, so Cancel is still there
  })

  it('a request that could not be sent says so, changes nothing, and can be tried again', async () => {
    const w = world()
    let down = true
    const server = w.server({ cancel: () => (down ? new Error('offline') : { status: 202, body: { ok: true, result: 'cancel_requested' } }) })
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(screen.text()).toContain('The cancel request could not be sent (The server could not be reached.). Nothing changed. Try again.')
    expect(screen.text()).not.toContain('Cancel requested. The run stops')
    down = false
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(screen.panel().textContent).toContain('Cancel requested.')
    expect(server.count(/POST/)).toBe(2)
  })

  it('a settled answer refreshes the live view so the screen shows what is true now', async () => {
    const w = world()
    const server = w.server({ cancel: () => { w.finish({ status: 'ok' }); return { status: 200, body: { ok: true, result: 'already_finished', message: 'This run has already finished. Nothing changed.' } } } })
    const screen = await mount(server)
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(server.count(/runs\/run0009/)).toBe(2)
    expect(screen.panel()).toBeNull()
    expect(screen.text()).toContain('This run has already finished. Nothing changed.')
  })
})

describe('a run that ends while the tab is hidden', () => {
  it('is found on return: the final state at once, the list read once, and no polling after', async () => {
    const w = world({ events: [ev('run_start')] })
    const server = w.server()
    const screen = await mount(server)
    expect(server.count(/runs\/run0009/)).toBe(1)
    expect(server.count(/GET \/api\/runs\?/)).toBe(1)
    await visibility('hidden')
    w.finish({ status: 'ok', steps: [{ name: 'discovery', status: 'ok', exitCode: 0 }, { name: 'scoring', status: 'ok', exitCode: 0 }], import: importBlock() })
    await tick(10 * 60 * 1000)
    expect(server.count(/runs\/run0009/)).toBe(1)
    expect(server.count(/GET \/api\/runs\?/)).toBe(1)
    await visibility('visible')
    expect(server.count(/runs\/run0009/)).toBe(2)
    expect(server.count(/GET \/api\/runs\?/)).toBe(2)
    expect(screen.panel()).toBeNull()
    expect(screen.cards()[0].textContent).toContain('OK')
    await tick(10 * 60 * 1000)
    await visibility('hidden')
    await visibility('visible')
    expect(server.count(/runs\/run0009/)).toBe(2)
    expect(server.count(/GET \/api\/runs\?/)).toBe(2)
  })

  it('a dead record (nothing holds the lock) is shown as interrupted, with no cancel button', async () => {
    const w = world({ alive: false })
    const server = w.server()
    const screen = await mount(server)
    expect(screen.panel()).toBeNull() // the list already says interrupted: nothing to follow
    expect(screen.cards()[0].textContent).toContain('Interrupted')
    expect(screen.text()).toMatch(/nothing is holding the run lock/)
    expect(screen.button(/Cancel run/)).toBeUndefined()
    await tick(60000)
    expect(server.count(/runs\/run0009/)).toBe(0)
  })
})
