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
