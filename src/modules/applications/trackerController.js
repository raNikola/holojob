/**
 * What the job-details tracker panel does, as plain functions so it can be tested without a
 * browser (docs/redesign/TRACKER_PLAN.md 3.3). Every write goes to the application store through
 * `applicationsClient`; nothing here touches `job.applicationTracking`.
 */

import { OUTCOMES } from './applicationEnums.js'
import * as client from './applicationsClient.js'
import { foldApplication } from './foldApplication.js'
import { legacyKind, legacyProblem } from './legacyTracking.js'
import { moveTargets } from './stageRegistry.js'
import { applicationsForJob, latestActiveApplication } from './trackingView.js'

/** Outcomes the panel sets on an open application. Rejected and Ghosted are board columns (`move`). */
export const PANEL_OUTCOMES = OUTCOMES.filter((o) => o !== 'rejected' && o !== 'ghosted')

/**
 * What the panel shows for a job:
 * - `loading` / `error`: no form at all (an empty cache would make every legacy job look new);
 * - `migrate-first`: the job still has old tracking and no application, so no new entry is allowed
 *   (it would sit next to the record the migration is about to create);
 * - `new`: nothing recorded yet;
 * - `tracked`: one or more attempts.
 */
export function panelMode(job, cache) {
  if (cache.status === 'error') return { mode: 'error', message: cache.error }
  if (cache.status !== 'ready') return { mode: 'loading' }
  const attempts = applicationsForJob(cache.store, job.jobId)
  if (attempts.length) return { mode: 'tracked', attempts, current: latestActiveApplication(attempts) ?? attempts[attempts.length - 1] }
  if (legacyKind(job) === 'candidate') return { mode: 'migrate-first', reason: legacyProblem(job) }
  return { mode: 'new', attempts: [] }
}

const today = () => new Date().toISOString().slice(0, 10)

/**
 * Record "applied". `form.requestId` is made once when the form opens, so a retry or a double click
 * returns the first result. `form.separateAttempt` names the reason when the user insists on a second,
 * different attempt after a 409.
 */
export async function markApplied(job, cache, form) {
  const mode = panelMode(job, cache)
  if (mode.mode === 'migrate-first') throw new client.ClientError(409, 'Run the migration first (Settings): this job still has tracking in the old format')
  if (mode.mode !== 'new' && mode.mode !== 'tracked') throw new client.ClientError(0, 'The tracker is not loaded')
  const body = {
    requestId: form.requestId,
    jobId: job.jobId,
    posting: job,
    attempt: {
      channel: form.channel,
      channelDetail: form.channelDetail ?? '',
      applicationUrl: form.applicationUrl ?? '',
      appliedDate: form.appliedDate || today(),
      cv: { kind: 'unknown' },
    },
  }
  if (form.separateAttempt) body.newAttempt = { distinctReason: form.separateAttempt }
  return client.createApplication(body)
}

/** The value of the stage select for a folded application. */
export function stageValue(folded) {
  if (folded.outcome === 'rejected' || folded.outcome === 'ghosted') return folded.outcome
  if (folded.outcome) return `outcome:${folded.outcome}`
  return folded.stage
}

/** The select's options: board stages and closed columns, then (open applications only) the other outcomes. */
export function stageOptions(settings, folded) {
  const options = moveTargets(settings).map((key) => ({ value: key, kind: 'move' }))
  if (!folded.outcome) options.push(...PANEL_OUTCOMES.map((o) => ({ value: `outcome:${o}`, kind: 'outcome' })))
  else if (folded.outcome && !['rejected', 'ghosted'].includes(folded.outcome)) options.push({ value: stageValue(folded), kind: 'outcome' })
  return options
}

/** The panel's draft, from the application as the server last returned it. */
export function draftFrom(app) {
  const folded = foldApplication(app)
  const recruiter = folded.contacts.find((c) => c.role === 'recruiter') ?? null
  return {
    stage: stageValue(folded),
    appliedDate: folded.appliedDate ?? '',
    followUpDate: folded.followUpDate ?? '',
    recruiterName: recruiter?.name ?? '',
    recruiterEmail: recruiter?.email ?? '',
    recruiterLinkedIn: recruiter?.linkedin ?? '',
    newNote: '',
  }
}

/**
 * The calls that turn the server's current state into the draft. Computed against the application
 * as cached now, so a save that failed half way and is retried only sends what is still missing.
 */
export function planSave(app, draft) {
  const folded = foldApplication(app)
  const calls = []
  if (draft.stage !== stageValue(folded)) {
    if (draft.stage.startsWith('outcome:')) {
      if (folded.outcome) throw new client.ClientError(400, 'Reopen the application before setting another outcome')
      calls.push({ kind: 'event', event: { type: 'outcome_set', data: { outcome: draft.stage.slice(8) } } })
    } else {
      calls.push({ kind: 'move', body: { toStage: draft.stage } })
    }
  }
  if (draft.appliedDate && draft.appliedDate !== (folded.appliedDate ?? '')) {
    calls.push({ kind: 'event', event: { type: 'applied_date_corrected', data: { appliedDate: draft.appliedDate } } })
  }
  const follow = draft.followUpDate || ''
  if (follow !== (folded.followUpDate ?? '')) {
    calls.push({ kind: 'event', event: follow ? { type: 'follow_up_set', data: { dueDate: follow } } : { type: 'follow_up_done', data: {} } })
  }
  const recruiter = folded.contacts.find((c) => c.role === 'recruiter') ?? null
  const wanted = { name: draft.recruiterName, email: draft.recruiterEmail, linkedin: draft.recruiterLinkedIn }
  if (!recruiter) {
    if (Object.values(wanted).some((v) => v.trim())) calls.push({ kind: 'event', event: { type: 'contact_added', data: { role: 'recruiter', ...wanted } } })
  } else {
    const changed = Object.fromEntries(Object.entries(wanted).filter(([key, value]) => value !== (recruiter[key] ?? '')))
    if (Object.keys(changed).length) calls.push({ kind: 'event', event: { type: 'contact_updated', data: { contactId: recruiter.contactId, ...changed } } })
  }
  if (draft.newNote.trim()) calls.push({ kind: 'event', event: { type: 'note_added', data: { text: draft.newNote } } })
  return calls
}

/** Send the planned calls in order; stops at the first failure, which the caller shows. */
export async function saveDraft(appId, draft, cache = client.getApplicationsState()) {
  const app = cache.store?.applications?.[appId]
  if (!app) throw new client.ClientError(404, 'Application not found')
  const calls = planSave(app, draft)
  for (const call of calls) {
    if (call.kind === 'move') await client.moveApplication(appId, call.body)
    else await client.addEvent(appId, call.event)
  }
  return calls.length
}

export const voidApplication = (appId, reason) => client.addEvent(appId, { type: 'application_voided', data: { reason } })
export const restoreApplication = (appId, reason) => client.addEvent(appId, { type: 'application_restored', data: { reason } })

/** A follow-up reminder from the Outreach screen: an event on the job's current application. */
export async function scheduleFollowUp(jobId, date, cache = client.getApplicationsState()) {
  const current = cache.store && latestActiveApplication(applicationsForJob(cache.store, jobId))
  if (!current) throw new client.ClientError(409, 'This job has no application in the tracker yet; mark it applied in Job Details first')
  return client.addEvent(current.id, { type: 'follow_up_set', data: { dueDate: date } })
}

/** A request id for one apply form. `randomUUID` needs a secure context, which a home server over http is not. */
export function newRequestId() {
  const c = globalThis.crypto
  if (c?.randomUUID) {
    try { return c.randomUUID() } catch { /* fall through */ }
  }
  const bytes = c.getRandomValues(new Uint8Array(16))
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
