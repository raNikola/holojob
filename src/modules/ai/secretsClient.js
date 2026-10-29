import { clearLegacyAiKey, readLegacyAiKey } from './aiSettings.js'

/** Providers that take a key; the same list as scripts/secret-store.js. */
export const KEYED_AI_PROVIDERS = ['openai', 'openrouter', 'claude', 'gemini']

async function request(method, path, body, fetchImpl) {
  let res
  try {
    res = await fetchImpl(path, {
      method,
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    })
  } catch {
    return { ok: false, error: 'The server could not be reached' }
  }
  let data = null
  try {
    data = await res.json()
  } catch { /* no JSON body */ }
  if (!res.ok) return { ok: false, error: (typeof data?.error === 'string' && data.error) || `Server answered ${res.status}` }
  return { ok: true, data }
}

/** { ok, data: { ai: { <provider>: { set, source, last4, baseUrl, setAt } }, linkedin: { set, source, last4, setAt } } }. The server never returns a key. */
export function fetchSecretsStatus(fetchImpl = globalThis.fetch) {
  return request('GET', '/api/secrets', null, fetchImpl)
}

export function putAiSecret(provider, { key, baseUrl }, fetchImpl = globalThis.fetch) {
  return request('PUT', `/api/secrets/ai/${encodeURIComponent(provider)}`, { key, ...(baseUrl ? { baseUrl } : {}) }, fetchImpl)
}

export function deleteAiSecret(provider, fetchImpl = globalThis.fetch) {
  return request('DELETE', `/api/secrets/ai/${encodeURIComponent(provider)}`, null, fetchImpl)
}

/**
 * The one-time move of the key an older build left in this browser (BROWSER_STORAGE_POLICY, section 4).
 * The browser copy is cleared only after the server answered that the key is set in its store with the same
 * last 4 characters, and it is read back to confirm. Any failure leaves the browser value untouched.
 */
export async function moveLegacyKeyToServer({ provider, baseUrl }, { storage, fetchImpl = globalThis.fetch } = {}) {
  const legacy = readLegacyAiKey(storage)
  if (!legacy) return { ok: false, error: 'There is no key in this browser' }
  if (!KEYED_AI_PROVIDERS.includes(provider)) return { ok: false, error: 'Choose the provider this key belongs to' }
  const value = legacy.apiKey.trim()

  const stored = await putAiSecret(provider, { key: value, baseUrl }, fetchImpl)
  if (!stored.ok) return { ok: false, error: stored.error }

  const status = await fetchSecretsStatus(fetchImpl)
  const entry = status.ok ? status.data?.ai?.[provider] : null
  if (!entry?.set || entry.source !== 'store' || entry.last4 !== value.slice(-4)) {
    return { ok: false, error: 'The server did not confirm the key. It was left in this browser.' }
  }

  if (!clearLegacyAiKey(storage)) {
    return { ok: false, error: 'The key is on the server, but it could not be removed from this browser. Remove it by hand.', onServer: true }
  }
  return { ok: true }
}

export function putLinkedInSecret(liAt, fetchImpl = globalThis.fetch) {
  return request('PUT', '/api/secrets/linkedin', { li_at: liAt }, fetchImpl)
}

export function deleteLinkedInSecret(fetchImpl = globalThis.fetch) {
  return request('DELETE', '/api/secrets/linkedin', null, fetchImpl)
}
