import { buildExportProfile } from '../../utils/exportJson'
import { ensureApiAvailable } from '../../utils/apiAvailability.js'

export async function saveProfileToDataDir(profile) {
  const available = await ensureApiAvailable()
  if (!available) {
    return { ok: false, reason: 'API unavailable' }
  }
  try {
    const res = await fetch('/api/profile/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile: buildExportProfile(profile) }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || 'Save failed')
    return { ok: true, ...data }
  } catch (e) {
    return { ok: false, reason: e.message }
  }
}

/**
 * The import's backup: the browser's current profile is written, read back and kept by the server (data/backups/profile-import-*).
 * True only when the server says it verified the file; anything else, including an unreachable server, is false.
 */
export async function backupProfileForImport(profile) {
  try {
    if (!(await ensureApiAvailable())) return false
    const res = await fetch('/api/profile/backup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    })
    const data = await res.json().catch(() => ({}))
    return res.ok && data.ok === true && typeof data.sha256 === 'string'
  } catch {
    return false
  }
}

// --- the Review screen's sync check: the save and the server status are two separate questions -----------------------------------
//
// "Synced" used to be shown only when the save returned 200 AND a cached health probe said available, and a failure of either was
// silent. Now both calls are made every time, independently, and each answer is reported on its own, with the HTTP status or a short
// reason and a fixed hint chosen here from the status. Nothing the server sends back (body, message) and nothing from the profile is shown.

const HINTS = {
  0: 'the server could not be reached',
  403: 'the server refused this web address; open the app from an address listed in HOLOJOB_ALLOWED_ORIGINS',
  413: 'the request was too large for the server',
  415: 'the server did not accept the request type',
  429: 'the server is busy',
}

/** A short, fixed description of a failed call: its status (or "no answer") and a hint from the status alone. */
export function describeFailure(part) {
  const status = part.status ? `HTTP ${part.status}` : 'no answer'
  const hint = HINTS[part.status ?? 0] ?? (part.status >= 500 ? 'the server failed while handling it; check its log' : null)
  return hint ? `${status}: ${hint}` : status
}

async function call(fetchFn, url, init) {
  try {
    const res = await fetchFn(url, init)
    return { ok: res.ok, status: res.status, res }
  } catch {
    return { ok: false, status: 0, res: null }
  }
}

/**
 * Send the profile to the mirror and ask the server for its status, as two independent calls.
 * @returns {Promise<{ save: { ok: boolean, status: number }, health: { ok: boolean, status: number, reason?: string } }>}
 */
export async function syncProfileWithStatus(profile, { fetchFn = globalThis.fetch } = {}) {
  const [saved, probed] = await Promise.all([
    call(fetchFn, '/api/profile/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile: buildExportProfile(profile) }) }),
    call(fetchFn, '/api/pipeline/health'),
  ])
  const health = { ok: probed.ok, status: probed.status }
  if (probed.ok) {
    const body = await probed.res.json().catch(() => null)
    if (body?.available !== true) Object.assign(health, { ok: false, reason: 'the server says it is not available' })
  }
  return { save: { ok: saved.ok, status: saved.status }, health }
}

/**
 * The lines the Review screen shows for a sync result: each failure on its own line, and a failed status check never says the profile
 * was not saved when the save itself succeeded.
 * @returns {{ tone: 'ok' | 'warn' | 'error', text: string }[]}
 */
export function syncMessages(result) {
  const { save, health } = result
  const lines = []
  if (save.ok && health.ok) return [{ tone: 'ok', text: 'Synced to data/profile/candidate-profile.json' }]
  if (save.ok) lines.push({ tone: 'ok', text: 'Saved to data/profile/candidate-profile.json.' })
  else lines.push({ tone: 'error', text: `Not synced: the profile could not be saved to the server (${describeFailure(save)}).` })
  if (!health.ok) {
    const why = health.reason ?? describeFailure(health)
    lines.push({ tone: save.ok ? 'warn' : 'error', text: `Server status could not be confirmed (${why}).` })
  }
  return lines
}
