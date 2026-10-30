/**
 * Settings > Sources on the server (scripts/sources-handler.js -> python/job_discovery/source_settings.py). The
 * browser holds no copy: the switches and the consent time live in data/config/sources.json, and discovery reads them.
 */

/** Browser key the old Jobs-screen Joberty checkbox used. It is only read and removed here, never written. */
const LEGACY_DISCOVERY_OPTIONS_KEY = 'job-dashboard-discovery-options'

async function call(fetchImpl, path, init) {
  try {
    const res = await fetchImpl(path, init)
    const data = await res.json().catch(() => ({}))
    return { ok: res.ok, status: res.status, data }
  } catch (e) {
    return { ok: false, status: 0, data: { error: e.message } }
  }
}

export function fetchSources(fetchImpl = globalThis.fetch) {
  return call(fetchImpl, '/api/sources')
}

/** `boards`: { joberty: { active, consentAccepted? } }. 409 + needsConsent when switching on without consent. */
export function saveSources(boards, fetchImpl = globalThis.fetch) {
  return call(fetchImpl, '/api/sources', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ boards }),
  })
}

/** The old checkbox value this browser still holds, or null when there is none. */
export function readLegacyDiscoveryOptions(storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(LEGACY_DISCOVERY_OPTIONS_KEY)
    if (raw == null) return null
    try {
      return { value: JSON.parse(raw) }
    } catch {
      return { value: null }
    }
  } catch {
    return null
  }
}

/**
 * The one-time move of the old Jobs-screen checkbox to the server. The server switches Joberty on only for an explicit
 * `includeJoberty: true` and only when it holds no decision yet, with the migration time as consent. The browser copy
 * is removed only after the server answered; any failure leaves it for the next try. No key, no request.
 */
export async function migrateLegacyDiscoveryOptions({ storage = globalThis.localStorage, fetchImpl = globalThis.fetch } = {}) {
  const legacy = readLegacyDiscoveryOptions(storage)
  if (!legacy) return { ok: true, migrated: false, present: false }
  const result = await call(fetchImpl, '/api/sources/migrate-legacy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: legacy.value }),
  })
  if (!result.ok) return { ok: false, present: true, error: result.data?.error || result.data?.errors?.[0] || 'Server unavailable' }
  try {
    storage.removeItem(LEGACY_DISCOVERY_OPTIONS_KEY)
  } catch {
    // Harmless: the server records the move once and ignores a second one.
  }
  return { ok: true, present: true, migrated: result.data?.migrated === true }
}
