// @vitest-environment jsdom
// The must-have review screen, driven in jsdom against a stub of the server.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import MustReview from '../../src/components/calibration/MustReview.jsx'
import { isMustsHash, nextUnanswered } from '../../src/modules/calibration/mustClient.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const VERDICT = { status: 'MISSING', strength: 1, evidenceQuote: 'Engine evidence text' }
const line = (n, extra = {}) => ({
  itemId: `i0${n}`, jobId: `job${n}`, kind: 'skill', text: `Requirement ${n}`, postingQuote: `Quote ${n}`, label: null, reveal: null, ...extra,
})
const ads = Object.fromEntries([1, 2, 3].map((n) => [`job${n}`, { title: `Title ${n}`, company: `Acme ${n}`, jobUrl: `https://example.test/${n}`, description: `Full ad ${n}` }]))

let root
let container
let items
let saves
let failSave

function fakeFetch(url, init) {
  if (url === '/api/calibration/musts') return Promise.resolve({ ok: true, json: async () => ({ items: structuredClone(items), ads, progress: {} }) })
  const body = JSON.parse(init.body)
  saves.push(body)
  if (failSave) return Promise.resolve({ ok: false, status: 500, json: async () => ({ error: 'disk full' }) })
  const answer = { isMust: body.isMust, meets: body.meets, savedAt: 't' }
  const before = items.find((i) => i.itemId === body.itemId).label
  const first = before ? before.first : answer
  const label = { itemId: body.itemId, first, final: answer, changedAfterReveal: first.isMust !== answer.isMust || first.meets !== answer.meets }
  items = items.map((i) => (i.itemId === body.itemId ? { ...i, label, reveal: VERDICT } : i))
  return Promise.resolve({ ok: true, json: async () => ({ label, reveal: VERDICT }) })
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
  await act(async () => { root.render(createElement(MustReview, { fetchFn: fakeFetch })) })
  await settle()
}
const answerFirst = async () => {
  await click(choice('Is this really a must?', 0))
  await click(choice('Do I meet it?', 1))
}

beforeEach(() => {
  items = [line(1), line(2), line(3)]
  saves = []
  failSave = false
})
afterEach(() => { act(() => root.unmount()); container.remove() })

describe('the must-have review screen', () => {
  it('starts blind: the requirement and the ad, no engine verdict, and the save button waits for both answers', async () => {
    await mount()
    expect(container.querySelector('[data-testid=requirement]').textContent).toBe('Requirement 1')
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('0 of 3 answered')
    expect(container.querySelector('[data-testid=reveal]')).toBeNull()
    expect(container.textContent).not.toMatch(/The engine says|Engine evidence|MISSING|MET/)
    expect(button(/Save and show the engine/).disabled).toBe(true)
    await click(choice('Is this really a must?', 0))
    expect(button(/Save and show the engine/).disabled).toBe(true) // one answer is not enough
  })

  it('saves both answers and then shows the engine verdict and its evidence', async () => {
    await mount()
    await answerFirst()
    await click(button(/Save and show the engine/))
    expect(saves).toEqual([{ itemId: 'i01', isMust: 'yes', meets: 'partial' }])
    expect(container.querySelector('[data-testid=reveal]').textContent).toContain('Not found in the CV evidence')
    expect(container.textContent).toContain('Engine evidence text')
    expect(container.querySelector('[data-testid=progress]').textContent).toBe('1 of 3 answered')
    expect(button(/Save and show the engine/)).toBeUndefined() // answers are locked once saved
  })

  it('moves to the next unanswered line, still blind, with Next line', async () => {
    await mount()
    await answerFirst()
    await click(button(/Save and show the engine/))
    await click(button(/Next line/))
    expect(container.querySelector('[data-testid=requirement]').textContent).toBe('Requirement 2')
    expect(container.querySelector('[data-testid=reveal]')).toBeNull()
  })

  it('records a change made after the reveal and keeps the first answer', async () => {
    await mount()
    await answerFirst()
    await click(button(/Save and show the engine/))
    await click(button(/Change my answer/))
    await click(choice('Is this really a must?', 1))
    await click(button(/Save my change/))
    expect(saves[1]).toEqual({ itemId: 'i01', isMust: 'nice', meets: 'partial' })
    expect(container.textContent).toContain('Your first answer (Yes, a real must; Partly) is kept for the report.')
  })

  it('resumes at the first unanswered line and keeps the blind state when a save fails', async () => {
    items = [line(1, { label: { first: { isMust: 'yes', meets: 'yes' }, final: { isMust: 'yes', meets: 'yes' }, changedAfterReveal: false }, reveal: VERDICT }), line(2), line(3)]
    await mount()
    expect(container.querySelector('[data-testid=requirement]').textContent).toBe('Requirement 2')
    failSave = true
    await answerFirst()
    await click(button(/Save and show the engine/))
    expect(container.textContent).toContain('Your answer was not saved: disk full')
    expect(container.querySelector('[data-testid=reveal]')).toBeNull()
  })

  it('shows the full ad only on request and links to the original', async () => {
    await mount()
    expect(container.querySelector('[data-testid=description]')).toBeNull()
    await click(button(/Show the full ad/))
    expect(container.querySelector('[data-testid=description]').textContent).toBe('Full ad 1')
    expect(container.querySelector('a').getAttribute('rel')).toContain('noopener')
  })
})

describe('route and helpers', () => {
  it('recognises only its own direct route, not the review route', () => {
    expect(isMustsHash('#/calibration/musts')).toBe(true)
    expect(isMustsHash('#/calibration/musts/')).toBe(true)
    expect(isMustsHash('#/calibration')).toBe(false)
    expect(isMustsHash('#/jobs')).toBe(false)
  })

  it('finds the next unanswered line and wraps', () => {
    const list = [line(1, { label: {} }), line(2), line(3, { label: {} })]
    expect(nextUnanswered(list, 0)).toBe(1)
    expect(nextUnanswered(list, 2)).toBe(1)
    expect(nextUnanswered([line(1, { label: {} })], 0)).toBe(-1)
  })
})
