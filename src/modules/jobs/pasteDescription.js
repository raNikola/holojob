// Paste box for a discovered ad whose description is empty or thin (package 12). The text goes to the server only
// (`/api/jobs/description/paste`): it is stored in data/jobs/pasted_descriptions.json, the ad is re-scored with it
// (local, no model, no network) and the scored fields are patched back. Keep, notes, status and applications are owner fields.
import { getStoredJob, patchJob } from './jobsStore.js'
import { scoredPatch } from './manualScoring.js'

/** Same threshold as THIN_DESCRIPTION_CHARS in python/job_scoring/job_history.py. */
export const THIN_DESCRIPTION_CHARS = 200
export const MIN_PASTE_CHARS = 40

/** Offered for a discovered ad (not hand-entered) whose text is under the thin threshold. */
export const canPasteDescription = (job) =>
  Boolean(job && !job.manualEntry && job.provider !== 'manual' && String(job.description ?? '').trim().length < THIN_DESCRIPTION_CHARS)

const MESSAGES = {
  unreachable: 'The server could not be reached, so the text was not saved.',
  run_active: 'A job run is in progress. Try again when it has finished.',
  not_in_history: 'The job history no longer holds this ad, so the text was not saved.',
  no_intelligence: 'Generate your candidate intelligence first.',
  no_python: 'The scoring service is not available.',
  text_too_short: 'That is too short to be an ad. Paste the whole ad text.',
  text_too_long: 'That text is too long to store.',
  failed: 'The ad could not be re-scored. Its saved score is unchanged.',
}

/** @returns {Promise<{ ok: true, job: object } | { ok: false, reason: string, message: string }>} */
export async function pasteDescription(jobId, text, { fetchFn = globalThis.fetch } = {}) {
  if (!getStoredJob(jobId)) return { ok: false, reason: 'missing', message: 'The ad is no longer in your list.' }
  let status = 0
  let data = {}
  try {
    const res = await fetchFn('/api/jobs/description/paste', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobId, text }) })
    status = res.status
    data = await res.json().catch(() => ({}))
  } catch {
    // unreachable
  }
  if (!(status === 200 && data.ok && data.job)) {
    const reason = status === 0 ? 'unreachable' : MESSAGES[data.error] ? data.error : MESSAGES[data.field] ? data.field : 'failed'
    return { ok: false, reason, message: MESSAGES[reason] }
  }
  const patched = patchJob(jobId, scoredPatch(data.job))
  return patched.ok ? { ok: true, job: patched.job } : { ok: false, reason: 'missing', message: 'The ad is no longer in your list.' }
}
