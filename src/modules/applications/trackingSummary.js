/**
 * The read-only application summary of the quick view, as plain functions. It reads the same application store as the
 * Job Details panel (`panelMode`, `foldApplication`), so the drawer, the page and the board cannot disagree.
 */

import { foldApplication } from './foldApplication.js'
import { labelFor } from './stageRegistry.js'
import { panelMode } from './trackerController.js'

const titleCase = (value) => value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

/** A stored `YYYY-MM-DD` in the format the Applications board uses (`toLocaleDateString`); empty when there is none. */
export function formatAppDate(value) {
  if (!value) return ''
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  const date = day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString()
}

/** The CV as recorded: its label or file name, nothing when none was recorded. */
export function cvName(cv) {
  if (!cv || cv.kind === 'unknown') return ''
  return cv.label || cv.fileName || (cv.kind === 'external' ? 'A CV outside the app' : '')
}

/** The values of one application; an empty string means "not recorded" and the view shows a neutral placeholder. */
export function summarizeApplication(app, settings) {
  const folded = foldApplication(app)
  const recruiter = folded.contacts.find((c) => c.role === 'recruiter') ?? null
  return {
    stage: folded.outcome ? titleCase(folded.outcome) : labelFor(folded.stage, settings),
    appliedOn: formatAppDate(folded.appliedDate),
    followUp: formatAppDate(folded.followUpDate),
    cv: cvName(folded.cv),
    recruiter: recruiter?.name?.trim() ?? '',
    eventCount: (app.events ?? []).length,
    noteCount: folded.notes.length,
  }
}

/**
 * What the quick view shows for a job: `loading`, `error`, `migrate-first` (as the panel), `none` (no active
 * application: the Mark Applied button; `closed` says that only a voided one exists) or `summary` for the current attempt.
 */
export function drawerTracking(job, cache) {
  const mode = panelMode(job, cache)
  if (mode.mode !== 'tracked') return mode.mode === 'new' ? { kind: 'none', voidedOnly: false } : { ...mode, kind: mode.mode }
  const folded = foldApplication(mode.current)
  if (folded.voided) return { kind: 'none', voidedOnly: true }
  return { kind: 'summary', app: mode.current, summary: summarizeApplication(mode.current, cache.settings) }
}
