/**
 * Statistics computed from the application store alone (docs/redesign/TRACKER_PLAN.md 6e): voided
 * applications count nowhere. Nothing is estimated; when a fact is not recorded it is counted as
 * missing and the screen says so. Pure: no I/O, no clock.
 */

import { CHANNELS } from './applicationEnums.js'
import { daysInStage, foldApplication } from './foldApplication.js'
import { boardColumn, labelFor, retiredStages } from './stageRegistry.js'
import { applicationsForJob, latestActiveApplication } from './trackingView.js'
import { boardColumns } from './boardModel.js'

export const CHANNEL_LABELS = {
  company_site: 'Company site',
  job_board: 'Job board',
  email: 'E-mail',
  referral: 'Referral',
  recruiter_inbound: 'Recruiter reached out',
  agency: 'Agency',
  other: 'Other',
}

export const OUTCOME_LABELS = {
  offer_accepted: 'Offer accepted',
  offer_declined: 'Offer declined',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  ghosted: 'Ghosted',
  position_closed: 'Position closed',
}

const DAY = 86400000
const dayMs = (iso) => Date.parse(`${iso}T00:00:00Z`)
const isDay = (value) => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(dayMs(value))

/** The Monday (YYYY-MM-DD) of the week a day falls in. */
export function weekStart(iso) {
  const ms = dayMs(iso)
  const weekday = (new Date(ms).getUTCDay() + 6) % 7
  return new Date(ms - weekday * DAY).toISOString().slice(0, 10)
}

export function median(values) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  const value = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
  return Math.round(value * 10) / 10
}

const tally = (items) => {
  const counts = new Map()
  for (const item of items) counts.set(item.key, { ...item, count: (counts.get(item.key)?.count ?? 0) + 1 })
  return [...counts.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

/** How the CV of an application is named in a count; null when none was recorded. */
function cvIdentity(cv) {
  if (!cv || cv.kind === 'unknown') return null
  const label = cv.label || cv.fileName || cv.kind
  return { key: cv.cvLibraryId || cv.sha256 || `${cv.kind}:${label}`, label }
}

/** Consecutive weeks from the first to the last, with 0 for a week without applications. */
function weekSeries(days) {
  if (!days.length) return []
  const counts = new Map()
  for (const day of days) counts.set(weekStart(day), (counts.get(weekStart(day)) ?? 0) + 1)
  const weeks = [...counts.keys()].sort()
  const series = []
  for (let ms = dayMs(weeks[0]); ms <= dayMs(weeks[weeks.length - 1]); ms += 7 * DAY) {
    const week = new Date(ms).toISOString().slice(0, 10)
    series.push({ week, count: counts.get(week) ?? 0 })
  }
  return series
}

/**
 * @returns {{
 *   total: number, open: number,
 *   perStage: {key, label, count}[], perChannel: {key, label, count}[], perCv: {key, label, count}[],
 *   perWeek: {week, count}[], medianDaysInStage: {key, label, median, spells}[],
 *   outcomes: {key, label, count}[],
 *   missing: { appliedDate: number, channel: number, cv: number, stageDates: number },
 * }}
 */
export function applicationStatistics(store, settings, today) {
  const rows = Object.values(store?.applications ?? {})
    .map((app) => ({ app, folded: foldApplication(app) }))
    .filter(({ folded }) => !folded.voided)

  const columnLabel = (key) => (key === 'closed' ? 'Closed (other outcomes)' : labelFor(key, settings))
  const perStage = tally(rows.map(({ folded }) => {
    const key = boardColumn(folded, settings)
    return { key, label: columnLabel(key) }
  }))
  const order = [...boardColumns(settings).map((c) => c.key), 'closed', 'unfiled']
  perStage.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))

  const channelKnown = (app) => CHANNELS.includes(app.attempt?.channel)
  const perChannel = tally(rows.filter(({ app }) => channelKnown(app)).map(({ app }) => ({
    key: app.attempt.channel,
    label: CHANNEL_LABELS[app.attempt.channel] ?? app.attempt.channel,
  })))

  const cvs = rows.map(({ folded }) => cvIdentity(folded.cv))
  const perCv = tally(cvs.filter(Boolean))

  const applied = rows.map(({ folded }) => folded.appliedDate).filter(isDay)

  // every spell in a stage, finished or running; a spell with an unknown date is left out, not guessed
  const spells = new Map()
  let undated = 0
  for (const { folded } of rows) {
    for (const entry of folded.stageHistory) {
      const days = isDay(entry.from) ? daysInStage(entry, today) : null
      if (days === null || days < 0) {
        undated += 1
        continue
      }
      spells.set(entry.stage, [...(spells.get(entry.stage) ?? []), days])
    }
  }
  const known = [...boardColumns(settings).map((c) => c.key), ...retiredStages(settings).map((s) => s.key)]
  const medianDaysInStage = [...spells.keys()]
    .sort((a, b) => (known.indexOf(a) === -1 ? 99 : known.indexOf(a)) - (known.indexOf(b) === -1 ? 99 : known.indexOf(b)))
    .map((key) => ({ key, label: labelFor(key, settings), median: median(spells.get(key)), spells: spells.get(key).length }))

  const outcomes = tally(rows.filter(({ folded }) => folded.outcome).map(({ folded }) => ({
    key: folded.outcome,
    label: OUTCOME_LABELS[folded.outcome] ?? folded.outcome,
  })))

  return {
    total: rows.length,
    open: rows.filter(({ folded }) => !folded.outcome).length,
    perStage,
    perChannel,
    perCv,
    perWeek: weekSeries(applied),
    medianDaysInStage,
    outcomes,
    missing: {
      appliedDate: rows.length - applied.length,
      channel: rows.filter(({ app }) => !channelKnown(app)).length,
      cv: cvs.filter((c) => !c).length,
      stageDates: undated,
    },
  }
}

/** The stage filter's choices for the tracker table: the columns that hold at least one application, then "closed". */
export function stageFilterOptions(store, settings) {
  const used = new Set()
  for (const app of Object.values(store?.applications ?? {})) {
    const column = boardColumn(foldApplication(app), settings)
    if (column !== null) used.add(column)
  }
  const keys = [...boardColumns(settings).map((c) => c.key), 'closed', 'unfiled'].filter((k) => used.has(k))
  return keys.map((key) => ({ value: key, label: key === 'closed' ? 'Closed (other outcomes)' : labelFor(key, settings) }))
}

/** jobId -> board column of the job's latest non-voided application (null when all its attempts are voided). */
export function columnByJobId(store, settings) {
  const byJob = new Map()
  for (const jobId of new Set(Object.values(store?.applications ?? {}).map((a) => a.posting?.jobId).filter(Boolean))) {
    const current = latestActiveApplication(applicationsForJob(store, jobId))
    byJob.set(jobId, current ? boardColumn(foldApplication(current), settings) : null)
  }
  return byJob
}
