import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// importDeps imports the real API clients; none of them runs at import time.
const { INTELLIGENCE_STALE_KEY, SYNC_PENDING_KEY, clearIntelligenceStale, isIntelligenceStale, isSyncPending, realImportDeps, snapshotStore } = await import('../../src/modules/profile/importDeps.js')

const items = new Map()
let setItem
beforeEach(() => {
  items.clear()
  setItem = vi.fn((k, v) => { items.set(k, v) })
  vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem, removeItem: (k) => { items.delete(k) } })
})
afterEach(() => vi.unstubAllGlobals())

describe('browser storage holds flags only', () => {
  it('the Undo snapshot never touches browser storage and is a deep copy', () => {
    const profile = { basicProfile: { fullName: 'A' }, list: [1] }
    snapshotStore.saveBefore(profile)
    profile.list.push(2)
    snapshotStore.saveAfter({ x: 1 })
    expect(setItem).not.toHaveBeenCalled()
    expect(snapshotStore.load()).toEqual({ before: { basicProfile: { fullName: 'A' }, list: [1] }, after: { x: 1 } })
    snapshotStore.clear()
    expect(snapshotStore.load()).toBeNull()
  })

  it('only the two allow-listed flags are ever written, as "1", and cleared by removal', () => {
    const deps = realImportDeps()
    deps.setSyncPending(true)
    deps.markIntelligenceStale()
    expect([...items.keys()].sort()).toEqual([INTELLIGENCE_STALE_KEY, SYNC_PENDING_KEY].sort())
    expect([...items.values()]).toEqual(['1', '1'])
    expect(isSyncPending()).toBe(true)
    expect(isIntelligenceStale()).toBe(true)
    deps.setSyncPending(false)
    clearIntelligenceStale()
    expect(items.size).toBe(0)
  })

  it('a storage that throws never breaks the import: the flags just are not shown', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') } })
    const deps = realImportDeps()
    expect(() => { deps.setSyncPending(true); deps.markIntelligenceStale(); clearIntelligenceStale() }).not.toThrow()
    expect(isSyncPending()).toBe(false)
  })
})
