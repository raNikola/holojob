// @vitest-environment jsdom
// Smoke: Settings > Sources lets the owner switch a source off, and Save sends exactly that change to the server.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import JobBoardsPanel from '../../src/components/settings/JobBoardsPanel.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const BOARDS = [
  { name: 'jobspy', optIn: false, inStandardRun: true, active: true },
  { name: 'infostud', optIn: false, inStandardRun: true, active: true },
  { name: 'joberty', optIn: true, inStandardRun: false, active: false },
]
let root
let container
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

describe('Settings > Sources panel', () => {
  it('has enabled switches and saves a switched-off LinkedIn (JobSpy) to the server', async () => {
    const puts = []
    vi.stubGlobal('localStorage', { getItem: () => null, setItem() {}, removeItem() {} })
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      if (init?.method === 'PUT') {
        puts.push(JSON.parse(init.body))
        return new Response(JSON.stringify({ ok: true, boards: BOARDS.map((b) => (b.name === 'jobspy' ? { ...b, active: false } : b)) }), { status: 200 })
      }
      return new Response(JSON.stringify({ boards: BOARDS }), { status: 200 })
    }))
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => { root.render(createElement(JobBoardsPanel)) })
    await act(async () => { await Promise.resolve() })
    const switches = [...container.querySelectorAll('button[role="switch"]')]
    expect(switches).toHaveLength(3)
    expect(switches.every((b) => !b.disabled)).toBe(true)
    const save = [...container.querySelectorAll('button')].find((b) => /Save sources/.test(b.textContent))
    expect(save.disabled).toBe(true)
    await act(async () => { switches.find((b) => /LinkedIn/.test(b.textContent)).click() })
    expect(save.disabled).toBe(false)
    await act(async () => { save.click() })
    await act(async () => { await Promise.resolve() })
    expect(puts).toEqual([{ boards: { jobspy: { active: false } } }])
    expect(container.textContent).toContain('Skipped by you')
  })
})
