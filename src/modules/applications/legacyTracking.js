/**
 * The old per-job `applicationTracking` record and how the migration reads it
 * (docs/redesign/TRACKER_PLAN.md 1.4 and 2.2). Pure: no I/O, no clock.
 */

/** The ten fields `applicationTracking.js` writes; anything else on a stored record is an unmapped key. */
export const LEGACY_FIELDS = [
  'applied', 'appliedDate', 'applicationUrl', 'recruiterName', 'recruiterEmail', 'recruiterLinkedIn',
  'notes', 'followUpDate', 'interviewStage', 'lastUpdated',
]

/** Legacy `interviewStage` value -> the event it becomes. `Applied` and an empty value become no event. */
export const LEGACY_STAGE_EVENTS = {
  'HR Screen': { type: 'stage_changed', key: 'stage', value: 'screen' },
  'Technical Round 1': { type: 'stage_changed', key: 'stage', value: 'tech' },
  'Technical Round 2': { type: 'stage_changed', key: 'stage', value: 'tech' },
  Assignment: { type: 'stage_changed', key: 'stage', value: 'tech' },
  'Hiring Manager': { type: 'stage_changed', key: 'stage', value: 'onsite' },
  'Final Round': { type: 'stage_changed', key: 'stage', value: 'onsite' },
  Offer: { type: 'stage_changed', key: 'stage', value: 'offer' },
  Rejected: { type: 'outcome_set', key: 'outcome', value: 'rejected' },
  Withdrawn: { type: 'outcome_set', key: 'outcome', value: 'withdrawn' },
}

/** `interviewStage` values that end the attempt (2.2, "already tracked"). Offer is open here. */
export const LEGACY_CLOSED_STAGES = ['Rejected', 'Withdrawn']

const isSet = (value) => value !== undefined && value !== null && value !== '' && value !== false

/** The tracking object of a job, or null when it has none. */
export function legacyTrackingOf(job) {
  const tracking = job?.applicationTracking
  return tracking && typeof tracking === 'object' && !Array.isArray(tracking) ? tracking : null
}

/**
 * Whether a record holds any value the user could have typed. `lastUpdated` is bookkeeping,
 * so a record that was opened and saved empty is not a candidate.
 */
export function hasLegacyValue(tracking) {
  return Object.entries(tracking ?? {}).some(([key, value]) => key !== 'lastUpdated' && isSet(value))
}

export function unmappedLegacyKeys(tracking) {
  return Object.keys(tracking ?? {}).filter((key) => !LEGACY_FIELDS.includes(key) && isSet(tracking[key]))
}

/** The event a legacy `interviewStage` maps to, or null. `unknown` is true for a value nobody maps. */
export function legacyStageEvent(interviewStage) {
  const value = typeof interviewStage === 'string' ? interviewStage : ''
  if (!value || value === 'Applied') return { event: null, unknown: false }
  const mapped = LEGACY_STAGE_EVENTS[value]
  if (!mapped) return { event: null, unknown: true }
  return { event: { type: mapped.type, data: { [mapped.key]: mapped.value, legacyStage: value } }, unknown: false }
}

/**
 * A legacy date as YYYY-MM-DD: the value itself, or the date part of an ISO timestamp. Anything
 * else gives `day: null` and `bad` (the original text), so a bad value never reaches the attempt.
 */
export function legacyDay(value) {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return { day: null, bad: null }
  const head = text.slice(0, 10)
  const parsed = new Date(`${head}T00:00:00Z`)
  const real = /^\d{4}-\d{2}-\d{2}$/.test(head) && !Number.isNaN(parsed.getTime())
    && parsed.toISOString().slice(0, 10) === head
  if (real && (text.length === 10 || /^\d{4}-\d{2}-\d{2}[T ]/.test(text))) return { day: head, bad: null }
  return { day: null, bad: text }
}

/** What kind of legacy job this is. The migration and the tracker panel both decide through this. */
export function legacyKind(job) {
  const tracking = legacyTrackingOf(job)
  if (job?.status === 'applied_manually') return 'candidate'
  if (job?.applicationTracking && !tracking) return 'candidate'
  return tracking && hasLegacyValue(tracking) ? 'candidate' : 'none'
}

/** Why a legacy candidate cannot be migrated, or null. (A duplicate id or a missing title are payload-level.) */
export function legacyProblem(job) {
  if (!/^[0-9a-f]{16}$/.test(typeof job?.jobId === 'string' ? job.jobId : '')) return 'jobId is not 16 hex characters'
  if (job.applicationTracking && !legacyTrackingOf(job)) return 'applicationTracking is not an object'
  return null
}

const sameValue = (a, b) => JSON.stringify(a ?? '') === JSON.stringify(b ?? '')

/**
 * The fields on which the legacy object a job carries now differs from the one that was migrated.
 * `lastUpdated` is bookkeeping and not compared. An incoming job with no object says nothing
 * (an import may have dropped it), so it gives no changes.
 */
export function legacyChanges(incoming, migrated) {
  if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) return []
  const before = migrated && typeof migrated === 'object' ? migrated : {}
  const keys = new Set([...Object.keys(incoming), ...Object.keys(before)])
  keys.delete('lastUpdated')
  return [...keys].filter((key) => !sameValue(incoming[key], before[key])).sort()
}
