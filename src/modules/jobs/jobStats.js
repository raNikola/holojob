import { fitScoreOf } from './matchScore.js'
import { isFollowUpDue } from './followUps'
import { TERMINAL_STAGES } from './applicationTracking'
import { isActionable } from './jobHistory'
import { onListJobs } from './jobFilters.js'

/** The Dashboard's count of jobs with a tailored resume, among current results. */
export function countTailoredResumes(jobs) {
  return onListJobs(jobs).filter((j) => j.tailoredAssets?.resumeMd || j.tailoredAssets?.resumePdf).length
}

/** Adds one application's tracking to the crm counts of `stats`. */
export function countTracking(stats, tracking) {
  if (tracking?.applied) stats.crmApplied += 1
  if (tracking?.interviewStage === 'Offer') stats.crmOffers += 1
  if (tracking?.interviewStage === 'Rejected') stats.crmRejected += 1
  if (
    tracking?.interviewStage
    && !TERMINAL_STAGES.has(tracking.interviewStage)
    && tracking.interviewStage !== 'Applied'
  ) {
    stats.crmInterviewing += 1
  }
  if (isFollowUpDue(tracking)) stats.crmFollowUpsDue += 1
}

export function computeJobStats(jobs) {
  const list = onListJobs(jobs)
  const stats = {
    total: list.length,
    new: 0,
    saved: 0,
    rejected: 0,
    applied_manually: 0,
    scored: 0,
    apply: 0,
    maybe: 0,
    skip: 0,
    p1: 0,
    p2: 0,
    p3: 0,
    avgScore: null,
    crmApplied: 0,
    crmInterviewing: 0,
    crmOffers: 0,
    crmRejected: 0,
    crmFollowUpsDue: 0,
  }

  let scoreSum = 0
  let scoreCount = 0

  for (const job of list) {
    const status = job.status || 'new'
    if (status in stats) stats[status] += 1

    if (fitScoreOf(job) !== null) {
      stats.scored += 1
      scoreSum += job.matchScore
      scoreCount += 1
    }
    // The action buckets count jobs worth acting on, so a closed ad is left out.
    const open = isActionable(job)
    if (open && job.applyRecommendation === 'Apply') stats.apply += 1
    if (open && job.applyRecommendation === 'Maybe') stats.maybe += 1
    if (job.applyRecommendation === 'Skip') stats.skip += 1
    if (open && job.priority === 'P1') stats.p1 += 1
    if (open && job.priority === 'P2') stats.p2 += 1
    if (job.priority === 'P3') stats.p3 += 1

    countTracking(stats, job.applicationTracking)
  }

  if (scoreCount > 0) {
    stats.avgScore = Math.round(scoreSum / scoreCount)
  }

  return stats
}
