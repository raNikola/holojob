// GET /api/jobs/all, held in memory only (slice S5e3a). Nothing here touches the stored job list or any browser storage: a failed
// answer changes nothing but this state, so it can never clear what the owner has.
import { useEffect, useSyncExternalStore } from 'react'

const IDLE = { status: 'idle', rows: null, meta: null, error: null }

/** The route's answer, or `{ ok: false, message }`. Never throws. A `rows` that is not a list is a failure, not an empty list. */
export async function fetchAllAds(fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn('/api/jobs/all')
    const body = await res.json().catch(() => null)
    if (res.ok && body?.ok === true && Array.isArray(body.rows)) return { ok: true, rows: body.rows, meta: body.meta ?? null }
    return { ok: false, message: body?.message || body?.error || `The list of all ads could not be loaded (${res.status})` }
  } catch (error) {
    return { ok: false, message: `The list of all ads could not be loaded: ${error.message}` }
  }
}

/** The state behind the hook: `loading`, `ready` or `error`. The last good rows stay through a later failure, and only the newest request counts. */
export function createAllAdsLoader({ fetchFn } = {}) {
  let state = IDLE
  let latest = 0
  const listeners = new Set()
  const set = (next) => {
    state = next
    listeners.forEach((listener) => listener())
  }
  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    async refetch() {
      const request = ++latest
      set({ ...state, status: 'loading' })
      const answer = await fetchAllAds(fetchFn ?? globalThis.fetch)
      if (request !== latest) return
      set(answer.ok
        ? { status: 'ready', rows: answer.rows, meta: answer.meta, error: null }
        : { ...state, status: 'error', error: answer.message })
    },
  }
}

const shared = createAllAdsLoader()

/** `{ status, rows, meta, error, refetch }`. Loads once when first used; `enabled: false` (no API, demo data) never asks. */
export function useAllAds({ enabled = true, loader = shared } = {}) {
  const state = useSyncExternalStore(loader.subscribe, loader.getState, loader.getState)
  useEffect(() => {
    if (enabled && loader.getState().status === 'idle') loader.refetch()
  }, [enabled, loader])
  return { ...state, refetch: loader.refetch }
}
