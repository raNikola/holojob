/**
 * The one list of paths that must never be exported in a backup nor written by a restore.
 * Paths are relative to the project root with forward slashes, e.g. "data/outreach/linkedin_session.json".
 */

const SECRET_DIRS = ['data/secrets', 'claude-config']

// A file name part that marks a credential: api_key.json, linkedin_session.json, token.txt, cookies.json, li_at ...
const SECRET_NAME = /(^|[-_.])(api[-_]?keys?|secrets?|tokens?|cookies?|sessions?|credentials?|passw(or)?d|li[-_]?at|id[-_]rsa)([-_.]|$)/i
const SECRET_EXT = /\.(pem|key|p12|pfx)$/i

/** Normalised relative path, or null when the name is absolute, contains "..", a NUL or a drive letter. */
export function safeRelativePath(name) {
  const raw = String(name ?? '')
  if (!raw || raw.includes('\0')) return null
  const slashed = raw.replace(/\\/g, '/')
  if (slashed.startsWith('/') || /^[A-Za-z]:/.test(slashed)) return null
  const parts = slashed.split('/').filter((p) => p !== '' && p !== '.')
  if (parts.includes('..')) return null
  return parts.join('/')
}

/** True when a backup must neither contain nor restore this path. Unsafe paths count as secret. */
export function isSecretPath(name) {
  const rel = safeRelativePath(name)
  if (rel === null) return true
  const lower = rel.toLowerCase()
  if (SECRET_DIRS.some((d) => lower === d || lower.startsWith(`${d}/`))) return true
  const parts = lower.split('/')
  const file = parts[parts.length - 1]
  if (file === '.env' || file.startsWith('.env.')) return true
  if (SECRET_EXT.test(file)) return true
  // Secret-looking names anywhere under data/ (data/config/ included): every part but the root "data".
  return parts.some((p, i) => (i > 0 || parts.length === 1) && SECRET_NAME.test(p))
}
