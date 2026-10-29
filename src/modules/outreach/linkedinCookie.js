import { fetchSecretsStatus, putLinkedInSecret } from '../ai/secretsClient.js'

/** Browser key an older build used for the LinkedIn cookie. It is only read and removed here, never written. */
const LEGACY_LINKEDIN_KEY = 'linkedin_li_at'

/** The cookie an older build left in this browser, or null. */
export function readLegacyLinkedInCookie(storage = globalThis.localStorage) {
  try {
    const value = storage?.getItem(LEGACY_LINKEDIN_KEY)
    return typeof value === 'string' && value.trim() ? value : null
  } catch {
    return null
  }
}

/** Remove the legacy cookie, then read it back. True only when it is really gone. */
export function clearLegacyLinkedInCookie(storage = globalThis.localStorage) {
  try {
    storage.removeItem(LEGACY_LINKEDIN_KEY)
  } catch {
    return false
  }
  return readLegacyLinkedInCookie(storage) === null
}

/**
 * The one-time move of the LinkedIn cookie an older build left in this browser (BROWSER_STORAGE_POLICY, section 4).
 * Same order as the AI key: the browser copy is removed only after the server answered that the cookie is set in its
 * store with the same last 4 characters, and it is read back to confirm. Any failure leaves the browser value untouched.
 */
export async function moveLegacyLinkedInToServer({ storage, fetchImpl = globalThis.fetch } = {}) {
  const legacy = readLegacyLinkedInCookie(storage)
  if (!legacy) return { ok: false, error: 'There is no LinkedIn cookie in this browser' }
  const value = legacy.trim()

  const stored = await putLinkedInSecret(value, fetchImpl)
  if (!stored.ok) return { ok: false, error: stored.error }

  const status = await fetchSecretsStatus(fetchImpl)
  const entry = status.ok ? status.data?.linkedin : null
  if (!entry?.set || entry.source !== 'store' || entry.last4 !== value.slice(-4)) {
    return { ok: false, error: 'The server did not confirm the cookie. It was left in this browser.' }
  }

  if (!clearLegacyLinkedInCookie(storage)) {
    return { ok: false, error: 'The cookie is on the server, but it could not be removed from this browser. Remove it by hand.', onServer: true }
  }
  return { ok: true }
}
