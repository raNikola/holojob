/**
 * The application store seen through the shape the older screens read
 * (docs/redesign/TRACKER_PLAN.md 3.2, `trackingFromApplication`). Pure. A derived value is
 * for display and statistics only: it must never be saved back into `job.applicationTracking`.
 */

import { foldApplication, isActive } from './foldApplication.js'
import { defaultSettings, labelFor } from './stageRegistry.js'

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
    return { ...job, applicationTracking: current ? trackingFromApplication(current, settings) : null }
  })
}
