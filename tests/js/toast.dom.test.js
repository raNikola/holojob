// @vitest-environment jsdom
// Toasts: the 15 s auto-hide with pause on hover/focus, keyboard dismissal, and the remembered dismissal of the storage notice.
import { createElement, act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOAST_AUTO_HIDE_MS, Toast, ToastStack } from '../../src/components/ui/Toast.jsx'
import StorageNotice, { DISMISSED_KEY } from '../../src/components/layout/StorageNotice.jsx'
import { resetStorageHealth, setStorageHealth } from '../../src/modules/jobs/storageHealth.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container
let root

function Host({ autoHideMs = null, onGone }) {
  const [open, setOpen] = useState(true)
  return createElement(ToastStack, null, open && createElement(Toast, { autoHideMs, onDismiss: () => { setOpen(false); onGone?.() } }, 'Hello toast'))
}
const mount = async (element) => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(element) })
}
const advance = (ms) => act(async () => { vi.advanceTimersByTime(ms) })
const toast = () => container.querySelector('[role=status],[role=alert]')
const fire = (el, type) => act(async () => { el.dispatchEvent(new MouseEvent(type, { bubbles: true })) })

beforeEach(() => { vi.useFakeTimers(); document.body.innerHTML = ''; resetStorageHealth(); window.localStorage.clear() })
afterEach(() => { act(() => root?.unmount()); vi.useRealTimers(); vi.restoreAllMocks() })

describe('Toast auto-hide', () => {
  it('goes after 15 s, not before', async () => {
    await mount(createElement(Host, { autoHideMs: TOAST_AUTO_HIDE_MS }))
    await advance(TOAST_AUTO_HIDE_MS - 1)
    expect(toast()).toBeTruthy()
    await advance(1)
    expect(toast()).toBeNull()
  })
  it('pauses while hovered and resumes with the time that was left', async () => {
    await mount(createElement(Host, { autoHideMs: TOAST_AUTO_HIDE_MS }))
    await advance(10000)
    await fire(toast(), 'mouseover') // React maps mouseenter from mouseover
    await advance(60000)
    expect(toast()).toBeTruthy()
    await fire(toast(), 'mouseout')
    await advance(4999)
    expect(toast()).toBeTruthy()
    await advance(1)
    expect(toast()).toBeNull()
  })
  it('pauses while focused, resumes on blur', async () => {
    await mount(createElement(Host, { autoHideMs: TOAST_AUTO_HIDE_MS }))
    const x = container.querySelector('button[aria-label=Dismiss]')
    await act(async () => { x.focus() })
    await advance(60000)
    expect(toast()).toBeTruthy()
    await act(async () => { x.blur() })
    await advance(TOAST_AUTO_HIDE_MS)
    expect(toast()).toBeNull()
  })
  it('a persistent toast (no autoHideMs) stays', async () => {
    await mount(createElement(Host))
    await advance(10 * 60000)
    expect(toast()).toBeTruthy()
  })
})

describe('Toast keyboard', () => {
  it('the X is a focusable button and dismisses', async () => {
    const onGone = vi.fn()
    await mount(createElement(Host, { onGone }))
    const x = container.querySelector('button[aria-label=Dismiss]')
    expect(x.tabIndex).toBe(0)
    await act(async () => { x.click() })
    expect(onGone).toHaveBeenCalledTimes(1)
    expect(toast()).toBeNull()
  })
  it('Escape on the focused toast dismisses it', async () => {
    await mount(createElement(Host))
    const x = container.querySelector('button[aria-label=Dismiss]')
    await act(async () => { x.focus() })
    await act(async () => { x.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    expect(toast()).toBeNull()
  })
})

describe('StorageNotice dismissal is remembered', () => {
  const lean = async () => {
    setStorageHealth({ level: 'lean' })
    document.body.innerHTML = ''
    await mount(createElement(StorageNotice))
  }
  it('a dismissed notice stays dismissed after a remount (localStorage)', async () => {
    await lean()
    expect(container.textContent).not.toBe('')
    await act(async () => { container.querySelector('button[aria-label=Dismiss]').click() })
    expect(container.textContent).toBe('')
    expect(JSON.parse(window.localStorage.getItem(DISMISSED_KEY))).toEqual(['lean'])
    act(() => root.unmount())
    await lean()
    expect(container.textContent).toBe('')
  })
  it('does not auto-hide', async () => {
    await lean()
    await advance(10 * 60000)
    expect(container.textContent).not.toBe('')
  })
  it('works, for this visit, when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    await lean()
    expect(container.textContent).not.toBe('')
    await act(async () => { container.querySelector('button[aria-label=Dismiss]').click() })
    expect(container.textContent).toBe('')
  })
  it('the error notice cannot be closed and is never remembered as dismissed', async () => {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(['error']))
    setStorageHealth({ level: 'error' })
    await mount(createElement(StorageNotice))
    expect(container.querySelector('[role=alert]')).toBeTruthy()
    expect(container.querySelector('button[aria-label=Dismiss]')).toBeNull()
  })
})
