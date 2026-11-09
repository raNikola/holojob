import { ensureApiAvailable } from '../../utils/apiAvailability'

/**
 * Asks the server to check its saved AI cover-letter draft against the profile and, only on a pass, make it a document.
 * The request is the job id and the confirmation; the text is the server's own copy, never sent from here.
 * Resolves { ok: true } or { ok: false, message, issues }.
 */
export async function acceptCoverLetter(jobId) {
  if (!(await ensureApiAvailable())) return { ok: false, message: 'The local API is not reachable.', issues: [] }
  try {
    const res = await fetch('/api/ai/cover-letter/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jobId, confirm: true }),
    })
    const body = await res.json().catch(() => ({}))
    if (res.ok && body.ok) return { ok: true }
    return { ok: false, message: body.message || 'The letter could not be checked.', issues: Array.isArray(body.issues) ? body.issues : [] }
  } catch {
    return { ok: false, message: 'The letter could not be checked.', issues: [] }
  }
}
