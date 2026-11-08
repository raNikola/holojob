// Manual Re-score of a kept ad (Wave 2 e). User-triggered only. The server scores the ad from its job history ledger with the
// same scorer a full run uses (local: no model, no network, so nothing for the AI budget gate to approve) and adds the row to
// scored_jobs.json. Here only the scored fields are patched onto the stored job: Keep, notes, status, applications and tailored
// assets are owner fields and stay as they are.
import { getJobsSnapshot, patchJob } from './jobsStore.js'
import { scoredPatch } from './manualScoring.js'

/** A kept or no-longer-listed ad has no scored copy for the server to tailor from, until the owner's Re-score gives it one. */
export const tailoringBlocked = (job) => Boolean((job.keptByUser || job.offList) && !(job.keptByUser && job.keptRescoredAt))

const MESSAGES = {
  unreachable: 'The server could not be reached, so the ad was not re-scored.',
  run_active: 'A job run is in progress. Try again when it has finished.',
  not_in_history: 'The job history no longer holds this ad, so it cannot be re-scored. Its saved score is unchanged.',
  no_intelligence: 'Generate your candidate intelligence first.',
  no_python: 'The scoring service is not available.',
  failed: 'The ad could not be re-scored. Its saved score is unchanged.',
}

async function post(url, body, fetchFn) {
  try {
    const res = await fetchFn(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    return { status: res.status, data: await res.json().catch(() => ({})) }
  } catch {
    return { status: 0, data: {} }
  }
}

/** @returns {Promise<{ ok: true, job: object } | { ok: false, reason: string, message: string }>} */
export async function rescoreKeptAd(jobId, { fetchFn = globalThis.fetch, now = () => new Date().toISOString() } = {}) {
  const stored = getJobsSnapshot().jobs.find((j) => j.jobId === jobId)
  if (!stored?.keptByUser) return { ok: false, reason: 'not_kept', message: 'Only a kept ad can be re-scored this way.' }
  const { status, data } = await post('/api/jobs/kept/rescore', { jobId }, fetchFn)
  if (!(status === 200 && data.ok && data.job)) {
    const reason = status === 0 ? 'unreachable' : MESSAGES[data.error] ? data.error : 'failed'
    return { ok: false, reason, message: MESSAGES[reason] }
  }
  const patched = patchJob(jobId, { ...scoredPatch(data.job), keptRescoredAt: now() })
  return patched.ok ? { ok: true, job: patched.job } : { ok: false, reason: 'missing', message: 'The ad is no longer in your list.' }
}

/**
 * Tells the server which ads this browser still keeps, so it forgets re-scored ads whose Keep was removed (ads with an
 * application are kept by the server itself). Best effort: a failure leaves the set as it was.
 */
export async function syncKeptIds({ fetchFn = globalThis.fetch } = {}) {
  const keptIds = getJobsSnapshot().jobs.filter((j) => j.keptByUser === true).map((j) => j.jobId)
  const { status, data } = await post('/api/jobs/kept/sync', { keptIds }, fetchFn)
  return status === 200 && data.ok
}
