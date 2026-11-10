// @vitest-environment jsdom
// The calibration review screen, driven in jsdom against a stub of the server.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import CalibrationReview from '../../src/components/calibration/CalibrationReview.jsx'
import { isCalibrationHash, nextUnreviewed, startingJudgment } from '../../src/modules/calibration/calibrationClient.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const proposal = { functionFit: 'yes', hardRequirements: 'unknown', overall: 2, reason: 'Reason one.', confidence: 'medium', missingInformation: [] }
const ad = (n, extra = {}) => ({
  jobId: `job${n}`, title: `Title ${n}`, company: `Acme ${n}`, location: 'Remote', site: 'x', jobUrl: `https://example.test/${n}`,
  description: `Full description ${n}`, proposal: n === 3 ? null : proposal, label: null, ...extra,
})

let root
let container
let items
let saves
let failSave

function fakeFetch(url, init) {
  if (url === '/api/calibration/review') return Promise.resolve({ ok: true, json: async () => ({ items: structuredClone(items), progress: {} }) })
  const body = JSON.parse(init.body)
  saves.push(body)
  if (failSave) return Promise.resolve({ ok: false, status: 500, json: async () => ({ error: 'disk full' }) })
  const label = { ...body, source: 'confirmed', savedAt: 't' }
  items = items.map((i) => (i.jobId === body.jobId ? { ...i, label } : i))
  return Promise.resolve({ ok: true, json: async () => ({ label }) })
}

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 10)) })
const button = (pattern) => [...container.querySelectorAll('button')].find((b) => pattern.test(b.textContent))
const choice = (legend, label) => [...container.querySelectorAll('fieldset')].find((f) => f.querySelector('legend').textContent === legend)
  .querySelectorAll('button')[label]
async function click(element) { await act(async () => { element.click() }); await settle() }
async function mount() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(CalibrationReview, { fetchFn: fakeFetch })) })
  await settle()
}

beforeEach(() => {
  items = [ad(1), ad(2), ad(3)]
  saves = []
  failSave = false
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('the review screen', () => {
  it('shows the ad in full, the AI suggestion and the progress, and no score', async () => {
    await mount()
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('0 of 3 reviewed')
    expect(container.querySelector('[data-testid=description]').textContent).toBe('Full description 1')
    expect(container.textContent).toContain('Reason one.')
    expect(container.textContent).not.toMatch(/score|weak band|P1|P2|Capped/i)
    expect(container.querySelector('a').getAttribute('rel')).toContain('noopener')
  })

  it('confirms the suggestion with one click, saves at once and moves on', async () => {
    await mount()
    await click(button(/Confirm the AI suggestion/))
    expect(saves).toEqual([{ jobId: 'job1', functionFit: 'yes', hardRequirements: 'unknown', overall: 2 }])
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('1 of 3 reviewed')
    expect(container.querySelector('[data-testid=description]').textContent).toBe('Full description 2')
  })

  it('saves a changed judgment, and an ad without a suggestion needs all three answers first', async () => {
    await mount()
    await click(button(/^Not relevant$/))
    expect(button(/Save my judgment/)).toBeTruthy() // touched: no longer a plain confirmation
    await click(button(/Save my judgment/))
    expect(saves[0]).toMatchObject({ jobId: 'job1', overall: 0 })
    await click(button(/Next ad/)) // job2, still open
    await click(button(/Next ad/)) // job3 has no suggestion
    expect(button(/Save my judgment/).disabled).toBe(true)
    await click(choice('Is it my kind of work?', 0))
    expect(button(/Save my judgment/).disabled).toBe(true) // two answers still missing
    await click(choice('Do I meet what is required?', 2))
    await click(choice('Would I apply?', 2))
    expect(button(/Save my judgment/).disabled).toBe(false)
  })

  it('resumes at the first ad that is not reviewed, and reads the labels back from the server', async () => {
    items = [ad(1, { label: { functionFit: 'no', hardRequirements: 'no', overall: 0 } }), ad(2), ad(3)]
    await mount()
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('1 of 3 reviewed')
    expect(container.querySelector('[data-testid=description]').textContent).toBe('Full description 2')
  })

  it('keeps the ad open and says so when a save fails', async () => {
    failSave = true
    await mount()
    await click(button(/Confirm the AI suggestion/))
    expect(container.textContent).toContain('Your judgment was not saved: disk full')
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('0 of 3 reviewed')
    expect(container.querySelector('[data-testid=description]').textContent).toBe('Full description 1')
  })
})

describe('helpers', () => {
  it('knows the direct route, the next open ad and a card\'s starting judgment', () => {
    expect(isCalibrationHash('#/calibration')).toBe(true)
    expect(isCalibrationHash('#/jobs/x')).toBe(false)
    expect(nextUnreviewed([{ label: {} }, {}, { label: {} }], 2)).toBe(1)
    expect(nextUnreviewed([{ label: {} }], 0)).toBe(-1)
    expect(startingJudgment({ label: { functionFit: 'no', hardRequirements: 'no', overall: 0 }, proposal })).toMatchObject({ functionFit: 'no' })
    expect(startingJudgment({ label: null, proposal: null })).toEqual({ functionFit: null, hardRequirements: null, overall: null })
  })
})
