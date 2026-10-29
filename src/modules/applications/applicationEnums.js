/**
 * Fixed value lists of the application tracker (docs/redesign/TRACKER_PLAN.md 1.4).
 * Shared by the server store (scripts/application-store.js) and the browser.
 */

/** Fixed stage keys (1.6): `applied` opens every application; `rejected` and `ghosted` are the closed columns. */
export const FIRST_STAGE = 'applied'
export const CLOSED_COLUMNS = ['rejected', 'ghosted']
export const UNFILED = 'unfiled'
/** Never used as a work stage key. */
export const RESERVED_STAGE_KEYS = [FIRST_STAGE, ...CLOSED_COLUMNS, UNFILED]

/** Work stages used when the tracker settings file does not exist. */
export const DEFAULT_WORK_STAGES = [
  { key: 'screen', label: 'Screen', retired: false, interview: false },
  { key: 'tech', label: 'Tech', retired: false, interview: true },
  { key: 'onsite', label: 'Onsite', retired: false, interview: true },
  { key: 'offer', label: 'Offer', retired: false, interview: false },
]

export const MAX_ACTIVE_WORK_STAGES = 10
export const MAX_STAGE_LABEL = 60
export const STAGE_KEY = /^[a-z0-9_]{1,40}$/

export const OUTCOMES = ['offer_accepted', 'offer_declined', 'rejected', 'withdrawn', 'ghosted', 'position_closed']

export const CHANNELS = ['company_site', 'job_board', 'email', 'referral', 'recruiter_inbound', 'agency', 'other']

export const DISTINCT_REASONS = ['reapply_after_outcome', 'different_channel', 'resubmitted_new_cv']

export const ORIGINS = ['manual', 'migration', 'csv']

export const EVENT_SOURCES = ['user', 'migration', 'csv', 'system']

export const CV_KINDS = ['library', 'tailored', 'external', 'unknown']

export const MESSAGE_VIA = ['email', 'linkedin', 'phone', 'other']

export const NUDGE_RULES = ['N0', 'N1', 'N2', 'N3', 'N4', 'N5']

export const CAPTURED_FROM = ['scored_jobs', 'job_history', 'browser', 'csv', 'manual']

export const EVENT_TYPES = [
  'applied',
  'stage_changed',
  'outcome_set',
  'outcome_cleared',
  'note_added',
  'contact_added',
  'contact_updated',
  'message_sent',
  'reply_received',
  'follow_up_set',
  'follow_up_done',
  'nudge_snoozed',
  'assignment_due',
  'offer_deadline',
  'event_voided',
  'application_voided',
  'application_restored',
  'applied_date_corrected',
  'cv_recorded',
]

/** Events that do not count as activity for nudges (section 5). */
export const NON_ACTIVITY_EVENTS = [
  'note_added',
  'nudge_snoozed',
  'event_voided',
  'application_voided',
  'application_restored',
  'applied_date_corrected',
  'cv_recorded',
]
