// @vitest-environment jsdom
// "Scoring behind" after a cancelled Re-scrape: a Re-score fixes the data, so the hook must be able to ask the server again.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRescrapeRun } from '../../src/modules/jobs/useRescrapeRun.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root
let container
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

describe('useRescrapeRun refresh', () => {
  it('clears scoringBehind when the server no longer reports it', async () => {
    let behind = true
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ run: null, active: false, scoringBehind: behind, events: [], next: 0 }) })))
    let hook
    const Probe = () => {
      hook = useRescrapeRun({ enabled: true, onFinished: () => {} })
      return null
    }
    container = document.createElement('div')
    root = createRoot(container)
    await act(async () => { root.render(createElement(Probe)) })
    expect(hook.view.scoringBehind).toBe(true)
    behind = false // a Re-score has written the matching run id
    await act(async () => { await hook.refresh() })
    expect(hook.view.scoringBehind).toBe(false)
  })
})
