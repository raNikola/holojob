/**
 * What the job-details tracker panel does, as plain functions so it can be tested without a
 * browser (docs/redesign/TRACKER_PLAN.md 3.3). Every write goes to the application store through
 * `applicationsClient`; nothing here touches `job.applicationTracking`.
 */

import { OUTCOMES } from './applicationEnums.js'
import * as client from './applicationsClient.js'
import { foldApplication } from './foldApplication.js'
import { legacyKind, legacyProblem } from './legacyTracking.js'
import { labelFor, moveTargets } from './stageRegistry.js'
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

const CV_FILE_ID = /^[a-f0-9]{16}$/
const baseName = (path) => String(path).split(/[/\\]/).pop()
export const UNKNOWN_CV = { key: 'unknown', kind: 'unknown', label: 'Not recorded yet' }
export const EXTERNAL_CV = { key: 'external', kind: 'external', label: 'A CV outside the app (name it)' }

/**
 * The CVs the user can say they sent. A library CV is offered only when its file was stored (a 16-hex id and a
 * `filePath`), because the store freezes a copy of the file and refuses a CV it cannot read. The tailored PDF is
 * named by `job.tailoredAssets` (bare file name), the same list the Resume Library shows.
 */
export function cvOptions(job, profile) {
  const options = []
  const tailored = job?.tailoredAssets?.resumePdf ? baseName(job.tailoredAssets.resumePdf) : null
  if (tailored) options.push({ key: 'tailored', kind: 'tailored', fileName: tailored, label: 'Tailored for this job' })
  for (const cv of profile?.cvLibrary ?? []) {
    if (!cv.filePath || !CV_FILE_ID.test(cv.id)) continue
    options.push({
      key: `library:${cv.id}`,
      kind: 'library',
      cvLibraryId: cv.id,
      fileName: cv.fileName || `${cv.label || 'cv'}.pdf`,
      label: `${cv.label || cv.fileName || 'CV'}${cv.id === profile.defaultCvId ? ' (default)' : ''}`,
    })
  }
  options.push(EXTERNAL_CV, UNKNOWN_CV)
  return options
}

/** The preselected option: tailored for this job, else the default library CV, else not recorded (TRACKER_PLAN 3.2). */
export function defaultCvOption(job, profile) {
  const options = cvOptions(job, profile)
  return options.find((o) => o.key === 'tailored')
    ?? options.find((o) => o.key === `library:${profile?.defaultCvId}`)
    ?? UNKNOWN_CV
}

/** The `attempt.cv` / `cv_recorded` fields for an option; the server decides the stored file name and sha256. */
function cvBody(option, label = '') {
  if (!option || option.kind === 'unknown') return { kind: 'unknown' }
  const body = { kind: option.kind }
  if (option.kind === 'library') body.cvLibraryId = option.cvLibraryId
  if (option.kind === 'library' || option.kind === 'tailored') body.fileName = option.fileName
  const text = (label || (option.kind === 'external' ? '' : option.label.replace(/ \(default\)$/, ''))).trim()
  if (text) body.label = text
  return body
}

/** Record which CV was sent (O4): a new event; a correction of an earlier record needs a reason. */
export async function recordCv(appId, option, { label = '', reason = '' } = {}, cache = client.getApplicationsState()) {
  if (!option || option.kind === 'unknown') throw new client.ClientError(400, 'Pick the CV that was sent')
  const app = cache.store?.applications?.[appId]
  if (!app) throw new client.ClientError(404, 'Application not found')
  const data = cvBody(option, label)
  if (foldApplication(app).cv?.kind !== 'unknown') {
    if (!reason.trim()) throw new client.ClientError(400, 'Correcting the recorded CV needs a reason')
    data.reason = reason.trim()
  }
  return client.addEvent(appId, { type: 'cv_recorded', data })
}

/** Link to a frozen file of an application (the server serves only names recorded on it). */
export const frozenFileUrl = (appId, fileName) => `/api/applications/${appId}/files/${encodeURIComponent(fileName)}`

const EVENT_TITLES = {
  applied: 'Applied',
  stage_changed: 'Stage changed',
  outcome_set: 'Closed',
  outcome_cleared: 'Reopened',
  note_added: 'Note added',
  contact_added: 'Contact added',
  contact_updated: 'Contact updated',
  message_sent: 'Message sent',
  reply_received: 'Reply received',
  follow_up_set: 'Follow-up set',
  follow_up_done: 'Follow-up done',
  nudge_snoozed: 'Reminder snoozed',
  assignment_due: 'Assignment due date',
  offer_deadline: 'Offer deadline',
  event_voided: 'Entry voided',
  application_voided: 'Application voided',
  application_restored: 'Application restored',
  applied_date_corrected: 'Applied date corrected',
  cv_recorded: 'CV recorded',
}

/** One timeline line for an event: a title and a short detail, newest first via `timeline`. */
export function describeEvent(event, settings) {
  const d = event.data ?? {}
  let detail
  switch (event.type) {
    case 'stage_changed': detail = d.stage ? labelFor(d.stage, settings) : ''; break
    case 'outcome_set': detail = d.outcome ?? ''; break
    case 'applied_date_corrected': detail = d.appliedDate ?? ''; break
    case 'follow_up_set': case 'assignment_due': case 'offer_deadline': detail = d.dueDate ?? ''; break
    case 'cv_recorded': detail = [d.kind, d.label || d.fileName, d.reason && `(${d.reason})`].filter(Boolean).join(' · '); break
    case 'note_added': detail = d.text ?? ''; break
    case 'application_voided': case 'application_restored': case 'outcome_cleared': detail = d.reason ?? ''; break
    default: detail = ''
  }
  return { id: event.id, date: event.date, title: EVENT_TITLES[event.type] ?? event.type, detail }
}

export const timeline = (app, settings) => [...(app.events ?? [])].reverse().map((event) => describeEvent(event, settings))

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
      cv: cvBody(form.cv, form.cvLabel),
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

const CALL_NAMES = {
  stage_changed: 'the stage', applied_date_corrected: 'the applied date', follow_up_set: 'the follow-up date', follow_up_done: 'the follow-up date',
  contact_added: 'the recruiter', contact_updated: 'the recruiter', note_added: 'the note', outcome_set: 'the outcome',
}
const callName = (call) => (call.kind === 'move' ? 'the stage' : CALL_NAMES[call.event.type] ?? call.event.type)

/**
 * Send the planned calls in order; stops at the first failure. The error names the step that failed and how many
 * landed before it (`extra.saved`), so a half-saved form is never silent. Returns the number of calls made.
 */
export async function saveDraft(appId, draft, cache = client.getApplicationsState()) {
  const app = cache.store?.applications?.[appId]
  if (!app) throw new client.ClientError(404, 'Application not found')
  const calls = planSave(app, draft)
  let saved = 0
  for (const call of calls) {
    try {
      if (call.kind === 'move') await client.moveApplication(appId, call.body)
      else await client.addEvent(appId, call.event)
    } catch (e) {
      const where = `Saving ${callName(call)} failed${saved ? ` (${saved} of ${calls.length} changes were saved)` : ''}: ${e.message}`
      throw new client.ClientError(e.status ?? 0, where, { ...(e.extra ?? {}), saved, planned: calls.length })
    }
    saved += 1
  }
  return calls.length
}

/**
 * The draft after the application changed under it (a CV recorded, a stage move, a note, a restore). A field the user
 * has not touched (still equal to the previous base) follows the new server value; an edited field is kept; the note
 * box is always kept. Without this, any event wiped what was typed and the form looked as if it did nothing.
 */
export function rebaseDraft(prevBase, draft, nextBase) {
  const next = { ...nextBase }
  for (const key of Object.keys(nextBase)) {
    if (key === 'newNote') next[key] = draft[key] ?? ''
    else if (draft[key] !== undefined && draft[key] !== prevBase[key]) next[key] = draft[key]
  }
  return next
}

/** What an error looks like on screen: the server's message, and its status when there is one. */
export function describeError(error) {
  if (error?.extra?.code === 'tracking_disabled') return 'Application tracking is switched off in the tracker settings.'
  const status = error?.status ? ` (HTTP ${error.status})` : ''
  return `${error?.message ?? 'Unknown error'}${status}`
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
