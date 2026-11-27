// Refresh a discovered ad's text from the employer's page (package 13). The server fetches the page and answers a line diff of the
// scraped text against the page text; the owner accepts or discards it. Accepting re-scores the ad locally (no model); the scraped
// original stays on the server. The page text never passes through the browser except as the diff lines shown here.
import { getStoredJob, patchJob } from './jobsStore.js'
import { scoredPatch } from './manualScoring.js'

const MESSAGES = {
  unreachable: 'The server could not be reached.',
  run_active: 'A job run is in progress. Try again when it has finished.',
  not_in_history: 'The job history no longer holds this ad.',
  no_intelligence: 'Generate your candidate intelligence first.',
  no_proposal: 'The fetched text is no longer on the server. Fetch it again.',
  url: 'Enter the address of the employer page.',
  failed: 'The request failed. Nothing was changed.',
}

/** Offered for a discovered ad (never a hand-entered one). */
export const canRefreshFromEmployer = (job) => Boolean(job && !job.manualEntry && job.provider !== 'manual')

async function post(path, body, fetchFn) {
  let status = 0
  let data = {}
  try {
    const res = await fetchFn(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    status = res.status
    data = await res.json().catch(() => ({}))
  } catch {
    // unreachable
  }
  return { status, data }
}

const failure = (status, data) => {
  const reason = status === 0 ? 'unreachable' : MESSAGES[data.error] ? data.error : MESSAGES[data.field] ? data.field : 'failed'
  return { ok: false, reason, message: data.message || MESSAGES[reason] }
}

/** @returns {Promise<{ ok: true, diff: object[], identical: boolean, truncated: boolean, finalUrl: string } | { ok: false, reason: string, message: string }>} */
export async function fetchEmployerText(jobId, url, { fetchFn = globalThis.fetch } = {}) {
  if (!getStoredJob(jobId)) return { ok: false, reason: 'missing', message: 'The ad is no longer in your list.' }
  const { status, data } = await post('/api/jobs/employer/fetch', { jobId, url }, fetchFn)
  if (status === 200 && data.ok) return { ok: true, diff: data.diff ?? [], identical: Boolean(data.identical), truncated: Boolean(data.truncated), finalUrl: data.finalUrl ?? '' }
  return failure(status, data)
}

export async function acceptEmployerText(jobId, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await post('/api/jobs/employer/accept', { jobId }, fetchFn)
  if (!(status === 200 && data.ok && data.job)) return failure(status, data)
  const patched = patchJob(jobId, scoredPatch(data.job))
  return patched.ok ? { ok: true, job: patched.job } : { ok: false, reason: 'missing', message: 'The ad is no longer in your list.' }
}

export async function discardEmployerText(jobId, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await post('/api/jobs/employer/discard', { jobId }, fetchFn)
  return status === 200 && data.ok ? { ok: true } : failure(status, data)
}
