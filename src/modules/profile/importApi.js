import { ensureApiAvailable } from '../../utils/apiAvailability.js'
import { buildExportProfile } from '../../utils/exportJson.js'

export const MAX_PASTE_BYTES = 200 * 1024

export function pasteSize(text) {
  return new TextEncoder().encode(text).length
}

/**
 * Ask the local API to read CV text into an import draft. The server parses and
 * writes nothing; the draft is only returned.
 * @param {'paste'|'resume_pdf'|'linkedin_pdf'} source
 * @param {string} text
 */
export async function parseImportText(source, text) {
  if (pasteSize(text) > MAX_PASTE_BYTES) throw new Error('The text is too large. The limit is 200 KB.')
  if (!(await ensureApiAvailable())) {
    throw new Error('Import requires the local API server (npm run dev or npm run start)')
  }
  const res = await fetch('/api/profile/import/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, text }),
  })
  let payload = null
  try { payload = await res.json() } catch { /* a non-JSON answer is reported below */ }
  if (!res.ok || !payload?.ok || !payload.draft) throw new Error(payload?.error || 'The text could not be read.')
  return payload.draft
}

export const parsePastedText = (text) => parseImportText('paste', text)

/**
 * What applying the import would do to the caches that depend on the profile (counts and profile versions, read-only on the server).
 * Never throws: `null` means "could not be worked out", and the confirm screen says so and still lets the owner apply.
 * @param {object} before the profile now
 * @param {object} after the profile the import would produce
 */
export async function fetchImportImpact(before, after) {
  try {
    if (!(await ensureApiAvailable())) return null
    const res = await fetch('/api/profile/import/impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ before: buildExportProfile(before), after: buildExportProfile(after) }),
    })
    const payload = await res.json().catch(() => null)
    return res.ok && payload?.ok && payload.impact ? payload.impact : null
  } catch {
    return null
  }
}

export const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
export const MAX_DOCX_BYTES = 10 * 1024 * 1024

/**
 * Send a Word document to the local API, which reads it and answers an import draft. The file is parsed in memory and is not stored.
 * @param {File} file
 */
export async function parseDocxFile(file) {
  if (file.size > MAX_DOCX_BYTES) throw new Error('The file is too large. The limit for a Word document is 10 MB.')
  if (!(await ensureApiAvailable())) throw new Error('Import requires the local API server (npm run dev or npm run start)')
  const res = await fetch('/api/profile/import/parse-docx', { method: 'POST', headers: { 'Content-Type': DOCX_MIME }, body: file })
  let payload = null
  try { payload = await res.json() } catch { /* a non-JSON answer is reported below */ }
  if (!res.ok || !payload?.ok || !payload.draft) throw new Error(payload?.error || 'The file could not be read.')
  return payload.draft
}
