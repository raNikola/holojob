// @vitest-environment jsdom
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it } from 'vitest'
import StorageNotice from '../../src/components/layout/StorageNotice.jsx'
import { resetStorageHealth, setStorageHealth } from '../../src/modules/jobs/storageHealth.js'
import { ERROR_NOTICE, LEAN_NOTICE, MINIMAL_NOTICE } from '../../src/modules/jobs/storageNoticeText.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container
const mount = async () => {
  container = document.createElement('div')
  document.body.appendChild(container)
  await act(async () => { createRoot(container).render(createElement(StorageNotice)) })
}
beforeEach(() => { document.body.innerHTML = ''; resetStorageHealth() })

describe('StorageNotice', () => {
  it('shows nothing when the list is stored whole', async () => {
    await mount()
    expect(container.textContent).toBe('')
  })
  it('near: a quiet note with the percent, nothing dropped', async () => {
    setStorageHealth({ level: 'near', percent: 88 })
    await mount()
    expect(container.textContent).toContain('about 88%')
    expect(container.textContent).toContain('Nothing has been dropped yet')
  })
  it('lean and minimal name what is kept and what is loaded from the server, and never say all AI results are kept', async () => {
    for (const [level, text] of [['lean', LEAN_NOTICE], ['minimal', MINIMAL_NOTICE(7)]]) {
      resetStorageHealth()
      setStorageHealth({ level, droppedText: 7 })
      document.body.innerHTML = ''
      await mount()
      expect(container.textContent).toContain(text)
      expect(text).toContain('notes, statuses, outreach, tracking, tailored assets and AI insights')
      expect(text).toMatch(/Loaded from the server instead:.*extracted facts and engine details/)
      expect(text).not.toMatch(/all (your )?AI results/i)
    }
  })
  it('error: permanent (no dismiss), says the change is not saved, never claims it was', async () => {
    setStorageHealth({ level: 'error' })
    await mount()
    expect(container.querySelector('[role="alert"]')).toBeTruthy()
    expect(container.textContent).toContain(ERROR_NOTICE)
    expect(container.textContent).not.toMatch(/\bsaved\.|has been saved|was saved/)
    expect([...container.querySelectorAll('button')].some((b) => /dismiss/i.test(b.textContent))).toBe(false)
  })
  it('lean can be dismissed', async () => {
    setStorageHealth({ level: 'lean' })
    await mount()
    await act(async () => { [...container.querySelectorAll('button')].find((b) => /dismiss/i.test(b.textContent)).click() })
    expect(container.textContent).toBe('')
  })
})
