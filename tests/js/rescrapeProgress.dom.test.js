// @vitest-environment jsdom
// The Jobs screen's progress line (S7c): a Details link to Activity, and the same Cancel as Activity's. The screen's own poll is not touched here.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RescrapeProgress from '../../src/components/jobs/RescrapeProgress.jsx'
import { OPEN_ACTIVITY_EVENT } from '../../src/modules/appNavigation.js'
import { emptyRunView } from '../../src/modules/jobs/rescrapeRun.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root
let container
const view = (over = {}, run = {}) => ({ ...emptyRunView(), run: { runId: 'abc123', status: 'running', orchestrator: 'rescrape', ...run }, active: true, ...over })
async function mount(v) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(RescrapeProgress, { view: v })) })
  const button = (pattern) => [...container.querySelectorAll('button')].find((b) => pattern.test(b.textContent))
  return { text: () => container.textContent, button, click: async (el) => { await act(async () => { el.click() }); await act(async () => { await Promise.resolve() }) } }
}
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  root = null
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubFetch(reply) {
  const fetchFn = vi.fn(async () => ({ ok: reply.status < 300, status: reply.status, json: async () => reply.body }))
  vi.stubGlobal('fetch', fetchFn)
  return fetchFn
}

describe('Details', () => {
  it('opens Activity', async () => {
    const heard = vi.fn()
    window.addEventListener(OPEN_ACTIVITY_EVENT, heard)
    const screen = await mount(view())
    await screen.click(screen.button(/^Details$/))
    window.removeEventListener(OPEN_ACTIVITY_EVENT, heard)
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('is there for a finished run too', async () => {
    const screen = await mount(view({ active: false }, { status: 'ok' }))
    expect(screen.button(/^Details$/)).toBeDefined()
  })

  it('shows nothing before any run', async () => {
    const screen = await mount(emptyRunView())
    expect(screen.text()).toBe('')
  })
})

describe('Cancel', () => {
  it('is offered for a Re-scrape that is going, and asks first', async () => {
    const fetchFn = stubFetch({ status: 202, body: { ok: true, result: 'cancel_requested' } })
    const screen = await mount(view())
    await screen.click(screen.button(/^Cancel run$/))
    expect(screen.text()).toContain('Cancel this run?')
    expect(fetchFn).not.toHaveBeenCalled()
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(fetchFn).toHaveBeenCalledTimes(1)
    expect(fetchFn.mock.calls[0][0]).toBe('/api/rescrape/cancel')
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ runId: 'abc123' })
    expect(screen.text()).toContain('Cancel requested. The run stops at its next safe point.')
    expect(screen.text()).not.toMatch(/Cancelled|has stopped/)
  })

  it('a double click sends one request', async () => {
    const fetchFn = stubFetch({ status: 202, body: { ok: true, result: 'cancel_requested' } })
    const screen = await mount(view())
    await screen.click(screen.button(/^Cancel run$/))
    const yes = screen.button(/Yes, cancel the run/)
    await act(async () => { yes.click(); yes.click() })
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['a pipeline or direct run', view({}, { orchestrator: undefined })],
    ['a run that has finished', view({ active: false }, { status: 'ok' })],
    ['a run that is already cancelled', view({ active: false }, { status: 'cancelled' })],
  ])('is not offered for %s', async (_name, v) => {
    const screen = await mount(v)
    expect(screen.button(/Cancel run/)).toBeUndefined()
  })

  it('is not offered again once the server says a cancel is on file, and the line says so once', async () => {
    const screen = await mount(view({ cancelRequested: true }))
    expect(screen.button(/Cancel run/)).toBeUndefined()
    expect(screen.text().match(/Cancel requested\. The run stops at its next safe point\./g)).toHaveLength(1)
  })

  it('says what the server said when nothing was requested, and keeps Cancel', async () => {
    stubFetch({ status: 200, body: { ok: true, result: 'already_finished', message: 'This run has already finished. Nothing changed.' } })
    const screen = await mount(view())
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(screen.text()).toContain('This run has already finished. Nothing changed.')
    expect(screen.text()).not.toContain('Cancel requested. The run stops')
  })

  it('says a refusal in red words and writes nothing to the browser', async () => {
    const write = vi.spyOn(Storage.prototype, 'setItem')
    stubFetch({ status: 409, body: { ok: false, result: 'not_cancellable', message: 'Only a Re-scrape can be cancelled. Nothing changed.' } })
    const screen = await mount(view())
    await screen.click(screen.button(/^Cancel run$/))
    await screen.click(screen.button(/Yes, cancel the run/))
    expect(screen.text()).toContain('Only a Re-scrape can be cancelled. Nothing changed.')
    expect(write).not.toHaveBeenCalled()
  })
})
