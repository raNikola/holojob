// @vitest-environment jsdom
// The polling hook of the live view (S7c): every 3 s while visible and active, nothing otherwise, back-off after errors.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BACKOFF_MS, POLL_MS, useLiveRun } from '../../src/modules/activity/useLiveRun.js'
import { fakeServer, live, running } from './setup/activityFixtures.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root
let container
let probe
const finished = vi.fn()

function Probe({ runId, fetchFn }) {
  probe = useLiveRun({ runId, fetchFn, onFinished: finished })
  return null
}

async function mount(fetchFn, runId = 'run0009') {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(Probe, { runId, fetchFn })) })
}
const advance = (ms) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
function visibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  return act(async () => { document.dispatchEvent(new window.Event('visibilitychange')) })
}

const going = () => live(running(9), { events: [] })
const over = () => live(running(9, { status: 'ok', finishedAt: '2026-11-01T09:20:00+00:00', orchestrator: 'rescrape' }))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
  finished.mockReset()
})
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  root = null
  vi.useRealTimers()
})

describe('polling', () => {
  it('asks at once, then every 3 s while the run is active, from the cursor it was given', async () => {
    let n = 0
    const server = fakeServer({ live: () => live(running(9), { events: [], next: ++n * 2 }) })
    await mount(server)
    expect(POLL_MS).toBe(3000)
    expect(server.calls.map((c) => c.url)).toEqual(['/api/runs/run0009?after=0'])
    await advance(2999)
    expect(server.calls).toHaveLength(1)
    await advance(1)
    expect(server.calls).toHaveLength(2)
    await advance(3000)
    expect(server.calls.map((c) => c.url)).toEqual(['/api/runs/run0009?after=0', '/api/runs/run0009?after=2', '/api/runs/run0009?after=4'])
    expect(finished).not.toHaveBeenCalled()
  })

  it('stops when the run is no longer active, after telling the screen once', async () => {
    let n = 0
    const server = fakeServer({ live: () => (++n < 3 ? going() : over()) })
    await mount(server)
    await advance(3000)
    await advance(3000)
    expect(server.calls).toHaveLength(3)
    expect(finished).toHaveBeenCalledTimes(1)
    expect(finished.mock.calls[0][0]).toMatchObject({ runId: 'run0009', status: 'ok' })
    expect(probe.finished).toBe(true)
    await advance(10 * 60 * 1000)
    expect(server.calls).toHaveLength(3)
    expect(finished).toHaveBeenCalledTimes(1)
  })

  it('a run that is already over when first asked is one request and one callback', async () => {
    const server = fakeServer({ live: over })
    await mount(server)
    await advance(60000)
    expect(server.calls).toHaveLength(1)
    expect(finished).toHaveBeenCalledTimes(1)
  })

  it('a run that is not there any more is finished, with no run to show', async () => {
    const server = fakeServer({ live: () => ({ status: 404, body: { ok: false, error: 'unknown_run' } }) })
    await mount(server)
    await advance(60000)
    expect(server.calls).toHaveLength(1)
    expect(finished).toHaveBeenCalledTimes(1)
    expect(finished).toHaveBeenCalledWith(null)
  })

  it('asks nothing without a run, and nothing after the screen is gone', async () => {
    const server = fakeServer({ live: going })
    await mount(server, null)
    await advance(60000)
    expect(server.calls).toHaveLength(0)
    await act(async () => root.unmount())
    root = null
    const second = fakeServer({ live: going })
    await mount(second)
    expect(second.calls).toHaveLength(1)
    await act(async () => root.unmount())
    root = null
    await advance(60000)
    expect(second.calls).toHaveLength(1)
    expect(finished).not.toHaveBeenCalled()
  })

  it('an answer that arrives after the screen is gone is dropped', async () => {
    let release
    const server = fakeServer({ live: () => new Promise((resolve) => { release = () => resolve(over()) }) })
    await mount(server)
    await act(async () => root.unmount())
    root = null
    await act(async () => { release() })
    expect(finished).not.toHaveBeenCalled()
  })
})

describe('the tab', () => {
  it('a hidden tab stops the timer, and showing it asks at once and starts again', async () => {
    const server = fakeServer({ live: going })
    await mount(server)
    expect(server.calls).toHaveLength(1)
    await visibility('hidden')
    await advance(5 * 60 * 1000)
    expect(server.calls).toHaveLength(1)
    await visibility('visible')
    expect(server.calls).toHaveLength(2)
    await advance(3000)
    expect(server.calls).toHaveLength(3)
  })

  it('a tab that is hidden when the screen opens asks nothing until it is shown', async () => {
    await visibility('hidden')
    const server = fakeServer({ live: going })
    await mount(server)
    await advance(60000)
    expect(server.calls).toHaveLength(0)
    await visibility('visible')
    expect(server.calls).toHaveLength(1)
  })

  it('a run that ends while the tab is hidden is found on return: one request, one callback, then nothing', async () => {
    let ended = false
    const server = fakeServer({ live: () => (ended ? over() : going()) })
    await mount(server)
    await visibility('hidden')
    ended = true
    await advance(10 * 60 * 1000)
    expect(server.calls).toHaveLength(1)
    expect(finished).not.toHaveBeenCalled()
    await visibility('visible')
    expect(server.calls).toHaveLength(2)
    expect(finished).toHaveBeenCalledTimes(1)
    expect(finished.mock.calls[0][0].status).toBe('ok')
    await advance(10 * 60 * 1000)
    await visibility('hidden')
    await visibility('visible')
    expect(server.calls).toHaveLength(2)
    expect(finished).toHaveBeenCalledTimes(1)
  })

  it('showing the tab while a request is on its way does not send a second', async () => {
    let release
    const server = fakeServer({ live: () => new Promise((resolve) => { release = () => resolve(going()) }) })
    await mount(server)
    await visibility('hidden')
    await visibility('visible')
    expect(server.calls).toHaveLength(1)
    await act(async () => { release() })
  })

  it('a tab hidden while a request is on its way does not schedule the next one', async () => {
    let release
    const server = fakeServer({ live: () => new Promise((resolve) => { release = () => resolve(going()) }) })
    await mount(server)
    await visibility('hidden')
    await act(async () => { release() })
    await advance(60000)
    expect(server.calls).toHaveLength(1)
  })
})

describe('after an error', () => {
  const down = () => new Error('offline')

  it('waits 3, 6, 12 and 30 s, and stays at 30', async () => {
    expect(BACKOFF_MS).toEqual([3000, 6000, 12000, 30000])
    const server = fakeServer({ live: down })
    await mount(server)
    expect(server.calls).toHaveLength(1)
    const waits = []
    for (const expected of [3000, 6000, 12000, 30000, 30000, 30000]) {
      const before = server.calls.length
      await advance(expected - 1)
      expect(server.calls.length, `before ${expected}`).toBe(before)
      await advance(1)
      expect(server.calls.length, `at ${expected}`).toBe(before + 1)
      waits.push(expected)
    }
    expect(waits).toEqual([3000, 6000, 12000, 30000, 30000, 30000])
    expect(finished).not.toHaveBeenCalled()
  })

  it('says it is trying again, and how soon', async () => {
    const server = fakeServer({ live: down })
    await mount(server)
    expect(probe.error).toBe('The server could not be reached.')
    expect(probe.retryInMs).toBe(3000)
    await advance(3000)
    expect(probe.retryInMs).toBe(6000)
  })

  it('a good answer ends the back-off: the next error waits 3 s again', async () => {
    let step = 0
    const script = [down, down, going, down, going]
    const server = fakeServer({ live: () => script[Math.min(step++, script.length - 1)]() })
    await mount(server)
    await advance(3000) // second error
    await advance(6000) // success
    expect(probe.error).toBeNull()
    await advance(3000) // the poll after a success is 3 s, and it fails
    expect(probe.retryInMs).toBe(3000)
    await advance(3000)
    expect(server.calls.length).toBe(5)
  })

  it('a 500 is an error to retry, not the end of the run', async () => {
    const server = fakeServer({ live: () => ({ status: 500, body: { ok: false } }) })
    await mount(server)
    await advance(3000)
    expect(server.calls).toHaveLength(2)
    expect(finished).not.toHaveBeenCalled()
  })

  it('never polls faster than 3 s, whatever happens', async () => {
    const times = []
    const server = fakeServer({ live: () => { times.push(Date.now()); return going() } })
    await mount(server)
    await advance(60000)
    for (let i = 1; i < times.length; i += 1) expect(times[i] - times[i - 1]).toBeGreaterThanOrEqual(3000)
    expect(times.length).toBe(21)
  })
})
