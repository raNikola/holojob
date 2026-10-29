/**
 * The current state of an application, computed from its event log
 * (docs/redesign/TRACKER_PLAN.md 1.2). Nothing here is stored, so it cannot
 * drift from the history. Pure: no I/O, no clock.
 */

import { NON_ACTIVITY_EVENTS } from './applicationEnums.js'

function bySeq(a, b) {
  return a.seq - b.seq
}

/** Ids of events cancelled by an `event_voided`. */
function voidedEventIds(events) {
  return new Set(events.filter((e) => e.type === 'event_voided').map((e) => e.data?.eventId))
}

export function foldApplication(app) {
  const events = [...(app?.events ?? [])].sort(bySeq)
  const cancelled = voidedEventIds(events)

  const state = {
    id: app?.id ?? null,
    voided: false,
    stage: 'applied',
    stageSince: null,
    stageHistory: [],
    outcome: null,
    outcomeDate: null,
    appliedDate: app?.attempt?.appliedDate ?? null,
    cv: app?.attempt?.cv ?? null,
    notes: [],
    contacts: [],
    followUpDate: null,
    assignmentDue: null,
    offerDeadline: null,
    snoozed: {},
    lastActivityDate: null,
    eventCount: events.length,
  }
  const contacts = new Map()
  // The stage reached, kept under an outcome; one entry per spell in a stage (reopening starts a new one).
  const history = [{ stage: 'applied', from: state.appliedDate, to: null }]
  const open = () => history[history.length - 1]

  for (const event of events) {
    // Void and restore always count: `event_voided` cannot target them.
    if (event.type === 'application_voided') state.voided = true
    if (event.type === 'application_restored') state.voided = false
    if (cancelled.has(event.id)) continue

    const data = event.data ?? {}
    switch (event.type) {
      case 'stage_changed':
        state.stage = data.stage
        state.stageSince = event.date
        if (open().to === null) open().to = event.date
        history.push({ stage: data.stage, from: event.date, to: null })
        break
      case 'outcome_set':
        state.outcome = data.outcome
        state.outcomeDate = event.date
        if (open().to === null) open().to = event.date
        break
      case 'outcome_cleared':
        state.outcome = null
        state.outcomeDate = null
        if (open().to !== null) history.push({ stage: state.stage, from: event.date, to: null })
        break
      case 'applied_date_corrected':
        state.appliedDate = data.appliedDate
        break
      case 'cv_recorded':
        // the reason stays in the history; the folded cv is the record itself
        state.cv = { ...data }
        delete state.cv.reason
        break
      case 'note_added':
        state.notes.push({ eventId: event.id, date: event.date, text: data.text })
        break
      case 'contact_added': {
        const { contactId, role, name, email, linkedin } = data
        contacts.set(contactId, { contactId, role, name, email, linkedin })
        break
      }
      case 'contact_updated': {
        const current = contacts.get(data.contactId)
        if (current) contacts.set(data.contactId, { ...current, ...data })
        break
      }
      case 'follow_up_set':
        state.followUpDate = data.dueDate
        break
      case 'follow_up_done':
        state.followUpDate = null
        break
      case 'nudge_snoozed':
        state.snoozed[data.rule] = data.until
        break
      case 'assignment_due':
        state.assignmentDue = data.dueDate
        break
      case 'offer_deadline':
        state.offerDeadline = data.dueDate
        break
      default:
        break
    }

    if (!NON_ACTIVITY_EVENTS.includes(event.type) && event.date
      && (!state.lastActivityDate || event.date > state.lastActivityDate)) {
      state.lastActivityDate = event.date
    }
  }

  // The first spell starts on the folded applied date, so a correction moves it.
  history[0].from = state.appliedDate
  state.stageSince ??= state.appliedDate
  state.stageHistory = history
  state.contacts = [...contacts.values()]
  return state
}

/** Whole calendar days from `from` to `to` (both YYYY-MM-DD); null when either is missing. */
export function daysBetween(from, to) {
  if (!from || !to) return null
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000)
}

/** Days spent in one stageHistory entry; an open entry runs to `today`. */
export function daysInStage(entry, today) {
  return daysBetween(entry.from, entry.to ?? today)
}

/**
 * Days in the stage the application is in now: from the newest stageHistory entry, which is the last
 * real entry into the stage (a reopen starts one, `stageSince` does not follow it). For a closed
 * application the entry ends on the day it closed.
 */
export function daysInCurrentStage(folded, today) {
  const entry = folded.stageHistory[folded.stageHistory.length - 1]
  return entry ? daysInStage(entry, today) : null
}

/** The one filter every list, count, nudge and duplicate check reads through (6e). */
export function isActive(app) {
  return !foldApplication(app).voided
}
