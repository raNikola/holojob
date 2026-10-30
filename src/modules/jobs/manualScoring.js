// Adding a hand-entered job and scoring it on the server. The server file is the master for the scored fields; this
// browser keeps its own copy of them and the owner's fields (notes, extra links, status, tracking), which never go over.
import { createJob, getJobsSnapshot, getStoredJob, patchJob } from './jobsStore.js'
import { buildManualJob, findDuplicateByUrl, scoringPayload } from './manualJob.js'

/** What the owner keeps: a scored record from the server never overwrites these. */
const OWNER_FIELDS = [
  'jobId', 'status', 'notes', 'extraLinks', 'manualEntry', 'sourceChoice', 'createdAt', 'firstSeen',
  'applicationTracking', 'updatedAt', 'tailoredAssets', 'outreach', 'aiInsights',
]

/** The scored fields of the server's record, to patch onto the stored job. */
export function scoredPatch(scored) {
  return Object.fromEntries(Object.entries(scored || {}).filter(([key]) => !OWNER_FIELDS.includes(key)))
}

export const NO_DESCRIPTION = 'No description: paste the ad text to score it.'

const MESSAGES = {
  unreachable: 'The server could not be reached, so the job was saved but not scored.',
  no_python: 'The scoring tools are not set up on the server, so the job was saved but not scored.',
  no_intelligence: 'Candidate intelligence is missing, so the job was saved but not scored. Generate it first, then score the job.',
  invalid: 'The server did not accept the job, so it was saved here but not scored.',
  failed: 'Scoring failed on the server, so the job was saved but not scored.',
}

async function post(path, body, fetchFn) {
  let response
  try {
    response = await fetchFn(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  } catch {
    return { status: 0, data: {} }
  }
  return { status: response.status, data: await response.json().catch(() => ({})) }
}

/**
 * Stores one manual job on the server and scores it (local scoring only). Sending the same job again is a retry.
 * @returns {Promise<{ ok: true, scored: object } | { ok: false, reason: 'duplicate', existing: object } | { ok: false, reason: string, message: string }>}
 */
export async function scoreOnServer(job, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await post('/api/jobs/manual/score', { job: scoringPayload(job) }, fetchFn)
  if (status === 200 && data.ok && data.jobs?.[0]) return { ok: true, scored: data.jobs[0] }
  if (status === 409 && data.existing) return { ok: false, reason: 'duplicate', existing: data.existing }
  const reason = status === 0 ? 'unreachable' : data.error === 'no_python' ? 'no_python' : data.error === 'no_intelligence' ? 'no_intelligence' : data.error === 'invalid' ? 'invalid' : 'failed'
  return { ok: false, reason, message: MESSAGES[reason] }
}

/** Write-nothing duplicate check against the server's discovered, scored and manual files (a job without text is not stored there). */
export async function checkOnServer(job, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await post('/api/jobs/manual/check', { job: scoringPayload(job) }, fetchFn)
  if (status === 409 && data.existing) return { ok: false, reason: 'duplicate', existing: data.existing }
  return { ok: true }
}

/**
 * Add job: checks this browser's list, asks the server (which also checks the discovered jobs), then creates the local
 * job, with the scored fields when scoring worked. A clash writes nothing here.
 * @returns {Promise<{ status: 'duplicate', existing: object } | { status: 'created', job: object, scored: boolean, message?: string }>}
 */
export async function addManualJob(form, { fetchFn = globalThis.fetch, apiAvailable = true, now, id } = {}) {
  const job = buildManualJob(form, { now, id })
  const local = findDuplicateByUrl(getJobsSnapshot().jobs, job.jobUrl)
  if (local) return { status: 'duplicate', existing: local }

  // Without the ad text nothing is stored or scored on the server (a title alone would rank on nothing); the link is still checked there.
  const hasText = Boolean(job.description)
  let result
  if (!hasText) {
    result = apiAvailable ? await checkOnServer(job, { fetchFn }) : { ok: true }
    if (!result.ok) return { status: 'duplicate', existing: result.existing }
    result = { ok: false, reason: 'no_description', message: NO_DESCRIPTION }
  } else {
    result = apiAvailable ? await scoreOnServer(job, { fetchFn }) : { ok: false, reason: 'unreachable', message: MESSAGES.unreachable }
  }
  if (!result.ok && result.reason === 'duplicate') return { status: 'duplicate', existing: result.existing }

  const created = createJob(result.ok ? { ...job, ...scoredPatch(result.scored) } : job)
  if (!created.ok) return { status: 'duplicate', existing: created.existing }
  return result.ok
    ? { status: 'created', job: created.job, scored: true }
    : { status: 'created', job: created.job, scored: false, message: result.message, noDescription: result.reason === 'no_description' }
}

/**
 * "Score now" / retry: sends the stored job again and patches the scored fields onto it. Safe to repeat: the server
 * replaces the row with the same id, and an unchanged patch writes nothing.
 * @returns {Promise<{ ok: true, job: object } | { ok: false, reason: string, message: string, existing?: object }>}
 */
export async function scoreStoredJob(jobId, { fetchFn = globalThis.fetch } = {}) {
  const stored = getStoredJob(jobId)
  if (!stored?.manualEntry) return { ok: false, reason: 'missing', message: 'This job is not a hand-entered job in your list.' }
  if (!String(stored.description ?? '').trim()) return { ok: false, reason: 'no_description', message: NO_DESCRIPTION }
  const result = await scoreOnServer(stored, { fetchFn })
  if (result.ok) {
    const patched = patchJob(jobId, scoredPatch(result.scored))
    return patched.ok ? { ok: true, job: patched.job } : { ok: false, reason: 'missing', message: 'The job is no longer in your list.' }
  }
  if (result.reason === 'duplicate') {
    return { ok: false, reason: 'duplicate', existing: result.existing, message: `This link is already in your jobs as “${result.existing.title || result.existing.jobId}”, so it was not scored again.` }
  }
  return result
}

/**
 * Hands this browser's manual jobs to the server before a scoring run, so a full Re-score includes the ones that were
 * saved while the server was away. Never throws and never blocks the run.
 */
export async function syncManualJobs({ fetchFn = globalThis.fetch } = {}) {
  // A job without its ad text is not handed over: scoring would rank it on the title alone.
  const jobs = getJobsSnapshot().jobs.filter((job) => job.manualEntry && String(job.description ?? '').trim())
  if (!jobs.length) return { ok: true, sent: 0 }
  const { status } = await post('/api/jobs/manual/sync', { jobs: jobs.map(scoringPayload) }, fetchFn)
  return { ok: status === 200, sent: jobs.length }
}
