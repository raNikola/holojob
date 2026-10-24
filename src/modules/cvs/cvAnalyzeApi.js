import { ensureApiAvailable } from '../../utils/apiAvailability'

async function post(url, body) {
  if (!(await ensureApiAvailable())) throw new Error('The local API is not reachable.')
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok || payload.ok === false) throw new Error(payload.error || 'CV analysis failed.')
  return payload
}

export function cvAnalysisInput(profile, cv) {
  const links = [...(cv.parsedData?.links || []), ...(profile.repositories?.githubLinks || [])]
  return { rawText: cv.rawText || '', fullName: profile.basicProfile?.fullName || '', links }
}

/** What would be sent, and to whom. Calls no model. */
export function previewCvAnalysis(input) {
  return post('/api/ai/cv-analyze/preview', input)
}

/** Sends the redacted CV to the provider. Only the confirm dialog calls this. */
export function runCvAnalysis(input, { force = false } = {}) {
  return post('/api/ai/cv-analyze', { ...input, confirm: true, force })
}
