// @vitest-environment jsdom
// The Activity screen (S7b), driven in jsdom with the server answered by a stub built from the real API projection.
import fs from 'node:fs'
import path from 'node:path'
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ActivityScreen from '../../src/components/activity/ActivityScreen.jsx'
import { api, fakeFetch, importBlock, proven, record, start } from './setup/activityFixtures.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const table = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, '../../src/data/proofReasons.json'), 'utf-8'))

let root
let container
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)) })

async function mount(fetchFn) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(ActivityScreen, { fetchFn })) })
  await settle()
  return {
    text: () => container.textContent,
    rows: () => [...container.querySelectorAll('[data-testid=run-row]')],
    button: (pattern, within = container) => [...within.querySelectorAll('button')].find((b) => pattern.test(b.textContent)),
    click: async (element) => { await act(async () => { element.click() }); await settle() },
    openAll: async () => { for (const button of [...container.querySelectorAll('button')].filter((b) => b.textContent === 'Details')) await act(async () => { button.click() }) },
  }
}

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setVisibility('visible')
})
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  root = null
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('the history', () => {
  it('asks once on open with limit=30 and shows one row per run with its figures', async () => {
    const fetchFn = fakeFetch(api([
      record(3, { import: importBlock({ saved: 455, new: 3, refreshed: 452 }), issues: [{ level: 'warning', source: null, message: 'Every source was skipped: no source searched in this run' }] }),
      record(2),
    ]))
    const screen = await mount(fetchFn)
    expect(fetchFn.calls).toEqual(['/api/runs?limit=30'])
    expect(screen.rows()).toHaveLength(2)
    const first = screen.rows()[0].textContent
    expect(first).toContain('Manual')
    expect(first).toContain('OK')
    expect(first).toContain('20 min 0 s')
    expect(first).toMatch(/Returned.*100/)
    expect(first).toMatch(/Collected.*40/)
    expect(first).toContain('455 (3 new)')
    expect(first).toMatch(/Filtered out.*60/)
    expect(first).toContain('1 issue')
    expect(screen.rows()[1].textContent).toContain('No issues')
    expect(screen.text()).toContain('Records older than 90 days are removed')
  })

  it('says Cancelled, Interrupted and Skipped in words, not only in a colour', async () => {
    const screen = await mount(fakeFetch(api([
      record(4, { status: 'cancelled', cancel: { requestedAt: start(4), outcome: 'collected_ads_saved', saved: 455 }, import: importBlock({ kind: 'partial', saved: 455, new: 3, refreshed: 452, ledger: undefined }) }),
      record(3, { status: 'interrupted', finishedAt: null }),
      record(2, { status: 'skipped', sources: [{ name: 'infostud', status: 'skipped', read: 0, kept: 0, new: 0, skipReason: "Infostud covers Serbia only, not 'Germany'" }] }),
      record(1, { status: 'partial' }),
      record(0, { status: 'failed' }),
    ])))
    const [cancelled, interrupted, skipped, partial, failed] = screen.rows().map((row) => row.textContent)
    expect(cancelled).toContain('Cancelled')
    expect(cancelled).toContain('The last run was cancelled. 455 collected ads were saved. Nothing else changed. Scoring was skipped.')
    expect(interrupted).toContain('Interrupted')
    expect(interrupted).toMatch(/stopped without finishing/)
    expect(skipped).toContain('Skipped')
    expect(skipped).toContain('Every source was skipped, so nothing was searched.')
    expect(partial).toContain('Partial')
    expect(failed).toContain('Failed')
  })

  it('Show more asks for the next cursor and adds the runs, and goes when there is no more', async () => {
    const first = Array.from({ length: 3 }, (_, i) => record(10 - i))
    const second = [record(5), record(10)] // run 10 again: shown once
    const fetchFn = fakeFetch(api(first, { next: '20261101T050000Z-run0008.json' }), api(second, { next: null }))
    const screen = await mount(fetchFn)
    expect(screen.rows()).toHaveLength(3)
    await screen.click(screen.button(/Show more/))
    expect(fetchFn.calls).toEqual(['/api/runs?limit=30', '/api/runs?limit=30&before=20261101T050000Z-run0008.json'])
    expect(screen.rows()).toHaveLength(4)
    expect(screen.button(/Show more/)).toBeUndefined()
  })

  it('a failed Show more says so beside the button and keeps the runs', async () => {
    const fetchFn = fakeFetch(api([record(2)], { next: '20261101T020000Z-run0002.json' }), { status: 500, body: { ok: false } })
    const screen = await mount(fetchFn)
    await screen.click(screen.button(/Show more/))
    expect(screen.rows()).toHaveLength(1)
    expect(screen.text()).toMatch(/run history is not available \(status 500\)\. Press Show more to try again/)
    expect(screen.button(/Show more/)).toBeDefined()
  })
})

describe('asks only when told to', () => {
  it('Refresh asks again, replaces the list, and nothing else does: no timer, no polling', async () => {
    const fetchFn = fakeFetch(api([record(1)]), api([record(2), record(1)]))
    const screen = await mount(fetchFn)
    vi.useFakeTimers({ toFake: ['setInterval', 'setTimeout'] })
    await act(async () => { vi.advanceTimersByTime(60 * 60 * 1000) })
    expect(fetchFn.calls).toHaveLength(1)
    vi.useRealTimers()
    await screen.click(screen.button(/Refresh/))
    expect(fetchFn.calls).toEqual(['/api/runs?limit=30', '/api/runs?limit=30'])
    expect(screen.rows()).toHaveLength(2)
  })

  it('has no timer in the code that fetches', () => {
    for (const file of ['src/modules/activity/useRunHistory.js', 'src/modules/activity/activityClient.js', 'src/components/activity/ActivityScreen.jsx']) {
      const code = fs.readFileSync(path.join(import.meta.dirname, '../..', file), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      expect(code, file).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|EventSource|WebSocket/)
    }
  })

  it('a hidden tab makes no request, and asks once when it is shown', async () => {
    setVisibility('hidden')
    const fetchFn = fakeFetch(api([record(1)]))
    const screen = await mount(fetchFn)
    expect(fetchFn.calls).toHaveLength(0)
    expect(screen.text()).toContain('Loading the run history')
    setVisibility('visible')
    await act(async () => { document.dispatchEvent(new window.Event('visibilitychange')) })
    await settle()
    expect(fetchFn.calls).toHaveLength(1)
    expect(screen.rows()).toHaveLength(1)
    for (const state of ['hidden', 'visible', 'hidden', 'visible']) {
      setVisibility(state)
      await act(async () => { document.dispatchEvent(new window.Event('visibilitychange')) })
    }
    expect(fetchFn.calls).toHaveLength(1)
  })

  it('stores nothing in the browser', async () => {
    const write = vi.spyOn(Storage.prototype, 'setItem')
    const screen = await mount(fakeFetch(api([record(1, { import: importBlock() })], { next: 'x' })))
    await screen.openAll()
    expect(write).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})

describe('states', () => {
  it('shows loading, then the empty state', async () => {
    let release
    const slow = async () => { await new Promise((resolve) => { release = resolve }); return { ok: true, status: 200, json: async () => ({ ok: true, runs: [], next: null, retentionDays: 90 }) } }
    const screen = await mount(slow)
    expect(screen.text()).toContain('Loading the run history')
    await act(async () => { release() })
    await settle()
    expect(screen.text()).toContain('No runs yet')
    expect(screen.text()).not.toContain('Loading the run history')
  })

  it('shows an error with a retry, and the retry works', async () => {
    const fetchFn = fakeFetch(new Error('offline'), api([record(1)]))
    const screen = await mount(fetchFn)
    expect(screen.text()).toContain('The run history could not be loaded')
    expect(screen.text()).toContain('The server could not be reached.')
    await screen.click(screen.button(/Try again/))
    expect(screen.text()).not.toContain('could not be loaded')
    expect(screen.rows()).toHaveLength(1)
  })

  it('a server error says its status', async () => {
    const screen = await mount(fakeFetch({ status: 503, body: { ok: false } }))
    expect(screen.text()).toContain('not available (status 503)')
  })

  it('an answer that is not the list is an error, not an empty history', async () => {
    const screen = await mount(fakeFetch({ status: 200, body: { ok: true } }))
    expect(screen.text()).toContain('could not be loaded')
    expect(screen.text()).not.toContain('No runs yet')
  })
})

describe('Details', () => {
  const richRun = () => record(5, {
    sources: [
      { name: 'jobspy', status: 'ok', read: 1001, kept: 574, new: 77, error: null, boardsFailed: [], skipReason: null, startedAt: start(5), finishedAt: start(5).replace(':00:00', ':02:30') },
      { name: 'infostud', status: 'failed', read: 0, kept: 0, new: 0, error: 'HTTPError 503 for CANARY at https://x.example', boardsFailed: [], skipReason: null },
      { name: 'joberty', status: 'skipped', read: 0, kept: 0, new: 0, error: null, boardsFailed: [], skipReason: "Joberty lists no ads for 'Germany'" },
      { name: 'greenhouse', status: 'ok', read: 9, kept: 4, new: 1, error: null, boardsFailed: ['broken'], skipReason: null },
    ],
    issues: Array.from({ length: 10 }, (_, i) => ({ level: i === 0 ? 'error' : 'warning', source: i === 0 ? 'infostud' : null, message: 'Every source was skipped: no source searched in this run' })),
    import: importBlock({
      saved: 455, new: 3, refreshed: 452,
      sources: [
        { name: 'jobspy', proof: { proven: true, why: ['proven'], boards: [] }, filterReasons: { title_not_matched: 400, location_not_matched: 22, country_not_matched: 3, not_listed: 1 } },
        { name: 'infostud', proof: { proven: false, why: ['source_failed', 'nothing_read'], boards: [] }, filterReasons: {} },
        { name: 'greenhouse', proof: { proven: false, why: ['boards_not_proven'], boards: [
          { board: 'acme', proven: true, why: ['board_complete'], detail: null },
          { board: 'beta', proven: false, why: ['total_differs'], detail: 'the answer reports 9 postings and 8 were read' },
        ] }, filterReasons: { title_not_matched: 5 } },
      ],
    }),
  })

  it('opens and closes, and shows the numbers apart, each with its help', async () => {
    const screen = await mount(fakeFetch(api([richRun()])))
    expect(container.querySelector('[data-testid=run-details]')).toBeNull()
    const toggle = screen.button(/^Details$/)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await screen.click(toggle)
    const details = screen.rows()[0].querySelector('[data-testid=run-details]')
    expect(details).not.toBeNull()
    const text = details.textContent
    for (const label of ['Returned', 'Filtered out', 'Collected', 'Saved', 'New', 'Refreshed']) expect(text).toContain(label)
    expect(text).toContain('Ads the source gave us, before your search rules were applied.')
    expect(text).toContain('Saved ads you already had, seen again.')
    expect(text).toContain('Saved 455 (3 new, 452 already known and refreshed)')
    expect(text).toContain('Duplicates merged: 5')
    expect(screen.button(/Hide details/).getAttribute('aria-expanded')).toBe('true')
    await screen.click(screen.button(/Hide details/))
    expect(screen.rows()[0].querySelector('[data-testid=run-details]')).toBeNull()
  })

  it('has the per-source table with its figures, reasons, proof, errors, skips and times', async () => {
    const screen = await mount(fakeFetch(api([richRun()])))
    await screen.openAll()
    const rows = Object.fromEntries([...screen.rows()[0].querySelectorAll('tbody tr')].map((tr) => [tr.querySelector('th').textContent, tr.textContent]))
    expect(Object.keys(rows)).toEqual(['jobspy', 'infostud', 'joberty', 'greenhouse'])
    expect(rows.jobspy).toContain('427') // 1001 returned - 574 collected
    expect(rows.jobspy).toContain("Title didn't match: 400, Location didn't match: 22, Country didn't match: 3 and 1 more")
    expect(rows.jobspy).toContain('Proven')
    expect(rows.jobspy).toContain(table.proven.text)
    expect(rows.jobspy).toContain('2 min 30 s')
    expect(rows.infostud).toContain('Failed')
    expect(rows.infostud).toContain('Not proven')
    expect(rows.infostud).toContain(table.source_failed.text)
    expect(rows.infostud).toContain(table.nothing_read.text)
    expect(rows.infostud).toContain('Error: Details withheld (HTTPError, HTTP 503)')
    expect(rows.infostud).not.toContain('CANARY')
    expect(rows.joberty).toContain('Skipped: ')
    expect(rows.joberty).toContain("Joberty lists no ads for 'Germany'")
    expect(rows.joberty).toContain('Not recorded') // no import row for this source: its proof is Not recorded, not Not proven
    expect(rows.joberty).not.toContain('Not proven')
    expect(rows.greenhouse).toContain('1 of 2 boards proven')
    expect(rows.greenhouse).toContain('beta: ' + table.total_differs.text)
    expect(rows.greenhouse).toContain('the answer reports 9 postings and 8 were read')
    expect(rows.greenhouse).toContain('Boards that failed: broken')
    expect(screen.rows()[0].textContent).toContain('do not add up to the run')
  })

  it('shows ledger effect, scoring, staging and the issues with their level', async () => {
    const screen = await mount(fakeFetch(api([richRun()])))
    await screen.openAll()
    const text = screen.rows()[0].querySelector('[data-testid=run-details]').textContent
    expect(text).toContain('1 closed, 2 marked absent, 0 reopened')
    expect(text).toMatch(/Scoring\s*Finished/)
    expect(text).toMatch(/Staging\s*Saved correctly/)
    expect(text).toContain('Error')
    expect(text).toContain('Warning')
    expect(text).toContain('infostud: Every source was skipped')
  })

  it('says how many issues are not shown', async () => {
    const issues = Array.from({ length: 14 }, () => ({ level: 'warning', source: null, message: 'Every source was skipped: no source searched in this run' }))
    const screen = await mount(fakeFetch(api([record(1, { issues })])))
    await screen.openAll()
    expect(screen.rows()[0].textContent).toContain('The first 10 of 14 issues are shown.')
  })

  it('a source that had not finished when the run was cancelled is Unfinished, never Failed', async () => {
    const cancelled = record(6, { status: 'cancelled', sources: [], steps: [{ name: 'discovery', status: 'cancelled', exitCode: 76 }], cancel: { requestedAt: start(6), outcome: 'collected_ads_saved', saved: 4 },
      import: importBlock({ kind: 'partial', complete: false, saved: 4, new: 2, refreshed: 2, ledger: undefined,
        sources: [{ name: 'jobspy', proof: { proven: false, why: ['not_finished', 'run_cancelled'], boards: [] }, filterReasons: {} }] }) })
    const screen = await mount(fakeFetch(api([cancelled])))
    await screen.openAll()
    const text = screen.rows()[0].textContent
    expect(text).toContain('Unfinished')
    expect(text).not.toContain('Failed')
    expect(text).toContain(table.not_finished.text)
    expect(text).toContain(table.run_cancelled.text)
    expect(text).toContain('Saved 4 (2 new, 2 already known and refreshed). Nothing else changed.')
    expect(text).toContain('Skipped because the run was cancelled')
  })
})

describe('old records: Not recorded, never 0, never Not proven', () => {
  it('shows what the record never held as Not recorded', async () => {
    const old = record(1, { steps: undefined })
    const screen = await mount(fakeFetch(api([old])))
    await screen.openAll()
    const details = screen.rows()[0].querySelector('[data-testid=run-details]')
    const figure = (label) => [...details.querySelectorAll('dl[aria-label="Numbers for this run"] > div')].find((div) => div.querySelector('dt').textContent === label).querySelector('dd').textContent
    expect(figure('Returned')).toBe('100')
    expect(figure('Collected')).toBe('40')
    expect(figure('Filtered out')).toBe('60')
    for (const label of ['Saved', 'New', 'Refreshed']) expect(figure(label), label).toBe('Not recorded')
    const text = screen.rows()[0].textContent
    expect(text).toContain('Saved: Not recorded')
    expect(text).not.toContain('Not proven')
    const source = details.querySelector('tbody tr').textContent
    expect(source).toContain('Not recorded')
    expect(details.textContent).toMatch(/Ledger effect\s*Not recorded/)
    expect(details.textContent).toMatch(/Scoring\s*Not recorded/)
    expect(screen.rows()[0].textContent).not.toMatch(/Saved \(new\)\s*0/)
  })

  it('a real zero is shown as 0, and only a real zero', async () => {
    const screen = await mount(fakeFetch(api([record(1, { sources: [{ name: 'jobspy', status: 'ok', read: 5, kept: 0, new: 0 }], import: importBlock({ saved: 0, new: 0, refreshed: 0 }) })])))
    expect(screen.rows()[0].textContent).toMatch(/Collected\s*0/)
    expect(screen.rows()[0].textContent).toContain('0 (0 new)')
  })
})

describe('every reason code', () => {
  it('is shown with the text from the shared file, in the state it belongs to', async () => {
    const codes = Object.keys(table)
    const records = codes.map((code, i) => {
      const ok = code === 'proven' || code === 'board_complete'
      return record(i, { sources: [{ name: 'jobspy', status: 'ok', read: 1, kept: 1, new: 0 }], import: importBlock({ sources: [{ name: 'jobspy', proof: { proven: ok, why: [code], boards: [] }, filterReasons: {} }] }) })
    })
    const screen = await mount(fakeFetch(api(records)))
    await screen.openAll()
    expect(screen.rows()).toHaveLength(codes.length)
    screen.rows().forEach((row, i) => {
      const entry = table[codes[i]]
      const cell = row.querySelector('tbody tr').textContent
      expect(cell, codes[i]).toContain(entry.text)
      expect(cell, codes[i]).toContain(entry.text.startsWith('Proven') ? 'Proven' : 'Not proven')
    })
  })
})
