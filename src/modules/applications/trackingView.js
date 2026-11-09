/**
 * The application store seen through the shape the older screens read
 * (docs/redesign/TRACKER_PLAN.md 3.2, `trackingFromApplication`). Pure. A derived value is
 * for display and statistics only: it must never be saved back into `job.applicationTracking`.
 */

import { foldApplication, isActive } from './foldApplication.js'
import { defaultSettings, labelFor } from './stageRegistry.js'
import { countTracking } from '../jobs/jobStats.js'

const OUTCOME_STAGE = {
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  ghosted: 'Ghosted',
  position_closed: 'Position closed',
  offer_accepted: 'Offer',
  offer_declined: 'Offer declined',
}

/** The applications recorded for one job, oldest first. Voided ones are included. */
export function applicationsForJob(store, jobId) {
  return Object.values(store?.applications ?? {})
    .filter((app) => app.posting?.jobId === jobId)
    .sort((a, b) => (a.createdAt === b.createdAt ? (a.id < b.id ? -1 : 1) : a.createdAt < b.createdAt ? -1 : 1))
}

/** The attempt a job row shows: the latest one that is not voided. */
export function latestActiveApplication(apps) {
  const active = apps.filter(isActive)
  return active.length ? active[active.length - 1] : null
}

/** The old `applicationTracking` shape, derived from an application's history. */
export function trackingFromApplication(app, settings = defaultSettings()) {
  const folded = foldApplication(app)
  const recruiter = folded.contacts.find((c) => c.role === 'recruiter') ?? folded.contacts[0] ?? null
  const last = app.events[app.events.length - 1]
  return {
    applied: true,
    appliedDate: folded.appliedDate ?? '',
    applicationUrl: app.attempt.applicationUrl ?? '',
    recruiterName: recruiter?.name ?? '',
    recruiterEmail: recruiter?.email ?? '',
    recruiterLinkedIn: recruiter?.linkedin ?? '',
    notes: folded.notes.map((n) => n.text).join('\n'),
    followUpDate: folded.followUpDate ?? '',
    interviewStage: folded.outcome ? OUTCOME_STAGE[folded.outcome] : labelFor(folded.stage, settings),
    lastUpdated: last?.at ?? '',
  }
}

/**
 * The jobs with `applicationTracking` taken from the store wherever the store has an application
 * for the job (none active = no tracking). Other jobs are returned as they are.
 */
export function overlayTracking(jobs, store, settings) {
  if (!store) return jobs
  return jobs.map((job) => {
    const apps = applicationsForJob(store, job.jobId)
    if (!apps.length) return job
    const current = latestActiveApplication(apps)
    if (!current) return { ...job, applicationTracking: null }
    // Applied is derived: the store has an active application, so the row shows it whatever the browser's stored status says.
    return { ...job, status: 'applied_manually', applicationTracking: trackingFromApplication(current, settings) }
  })
}

/** A frozen posting in the job shape the detail screens read. Only ad fields: no capture data, nothing of the application. */
export function jobFromPosting(posting) {
  const { jobId, title, company, location, url, source, provider, datePosted, salary, employmentType, workMode, isRemote, description } = posting
  return { jobId, title, company, location, jobUrl: url, source, provider, datePosted, salary, employmentType, workMode, isRemote, description }
}

/**
 * The crm counts of the stat cards, from the application store alone: an application counts whether or not its ad is
 * still in the browser's list. One per non-voided application, as the board and Application Statistics count (two
 * attempts at one job are two). Null before the store is loaded.
 */
export function trackerStats(store, settings) {
  if (!store) return null
  const stats = { crmApplied: 0, crmInterviewing: 0, crmOffers: 0, crmRejected: 0, crmFollowUpsDue: 0 }
  for (const app of Object.values(store.applications ?? {})) {
    if (isActive(app)) countTracking(stats, trackingFromApplication(app, settings))
  }
  return stats
}

/**
 * Jobs with an active application and no browser row, one per job, in the shape of an overlaid row, for display and
 * the application context. Derived on every call and never to be saved into the job list (`offList` keeps the same
 * rule): a saved row would count as an active job.
 */
export function applicationOnlyJobs(jobs, store, settings) {
  if (!store) return []
  const rows = new Set((jobs ?? []).map((job) => job.jobId))
  const latest = new Map()
  const sorted = Object.values(store.applications ?? {}).sort((a, b) => (a.createdAt === b.createdAt ? (a.id < b.id ? -1 : 1) : a.createdAt < b.createdAt ? -1 : 1))
  for (const app of sorted) {
    const jobId = app.posting?.jobId ?? null
    if (app.posting && !rows.has(jobId) && isActive(app)) latest.set(jobId ?? app.id, app)
  }
  return [...latest.values()].map((app) => ({
    ...jobFromPosting(app.posting),
    status: 'applied_manually',
    applicationId: app.id,
    applicationTracking: trackingFromApplication(app, settings),
  }))
}
