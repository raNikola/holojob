import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import { SIDEBAR_COLLAPSED_KEY, loadSidebarCollapsed, saveSidebarCollapsed } from '../../src/modules/sidebarState.js'

const memory = () => {
  const data = new Map()
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), data }
}

describe('sidebar collapsed state', () => {
  it('starts expanded when nothing is stored', () => {
    expect(loadSidebarCollapsed(memory())).toBe(false)
  })

  it('remembers collapsed and expanded across loads', () => {
    const store = memory()
    saveSidebarCollapsed(true, store)
    expect(loadSidebarCollapsed(store)).toBe(true)
    saveSidebarCollapsed(false, store)
    expect(loadSidebarCollapsed(store)).toBe(false)
    expect(store.data.get(SIDEBAR_COLLAPSED_KEY)).toBe('false')
  })

  it('reads anything but "true" as expanded', () => {
    const store = memory()
    store.setItem(SIDEBAR_COLLAPSED_KEY, 'maybe')
    expect(loadSidebarCollapsed(store)).toBe(false)
  })

  it('survives storage that is missing or throws', () => {
    const broken = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') } }
    expect(loadSidebarCollapsed(broken)).toBe(false)
    expect(() => saveSidebarCollapsed(true, broken)).not.toThrow()
    expect(loadSidebarCollapsed(null)).toBe(false)
    expect(() => saveSidebarCollapsed(true, null)).not.toThrow()
  })
})

describe('sidebar markup', () => {
  const src = fs.readFileSync('src/components/layout/Sidebar.jsx', 'utf8')

  it('is pinned to the viewport on desktop', () => {
    expect(src).toMatch(/md:sticky md:top-0/)
    expect(src).toMatch(/md:h-screen/)
  })

  it('leaves the mobile bottom nav as it was: compact buttons, never collapsed', () => {
    const mobile = src.slice(src.indexOf('fixed bottom-0'))
    expect(mobile).toContain('compact')
    expect(mobile).not.toContain('collapsed')
  })
})
