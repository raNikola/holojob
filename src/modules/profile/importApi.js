import { ensureApiAvailable } from '../../utils/apiAvailability.js'

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
