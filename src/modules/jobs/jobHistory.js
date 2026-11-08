/** Only an ad closed by the two-check rule (S5c) says so; one closed earlier, after a single absence, keeps the old wording. */
function closedReason(job) {
  if (!job.closedAt) return ''
  const date = job.closedAt.slice(0, 10)
  return job.closedAfterChecks ? `Not on the company's board in 2 complete checks since ${date}` : `No longer listed since ${date}`
}

/** Badges for a job's place in the discovery history: "Just found" (first seen recently, the `isNew` flag, not the triage status), or no longer listed. */
export function historyBadges(job) {
  const badges = []
  if (job?.isClosed) badges.push({ label: 'Closed', variant: 'low', reason: closedReason(job) })
  else if (job?.isStale) badges.push({ label: 'Stale', variant: 'low', reason: job.lastSeen ? `No sighting since ${formatSeen(job.lastSeen)}, across several successful runs` : '' })
  else if (job?.isAbsent) badges.push({ label: 'Not in latest search', variant: 'low', reason: job.absentSince ? `Not on the company's board in a complete check on ${job.absentSince.slice(0, 10)}. Last seen ${formatSeen(job.lastSeen)}` : '' })
  else if (job?.isNew) badges.push({ label: 'Just found', variant: 'high', reason: job.firstSeen ? `First seen ${job.firstSeen.slice(0, 10)}` : '' })
  return badges
}

/**
 * A job worth acting on now. Closed and Stale jobs stay visible, but are not candidates for "do something now" actions. `isStale` is on a
 * stored row; `class` is on a row of the composed list (allAds.js).
 */
export function isActionable(job) {
  return !job?.isClosed && !job?.isStale && job?.class !== 'stale' && job?.class !== 'closed'
}

/** The ad itself is closed. Nothing about the application: an application keeps its own status. The route's class wins over a stored mark that may be older. */
export function isClosedAd(row) {
  return row?.class ? row.class === 'closed' : row?.isClosed === true
}

/** Said on an application whose ad has closed: the application itself is untouched. */
export const AD_CLOSED_NOTE = 'The ad is no longer listed. This says nothing about your application, which keeps its own status.'

/** The job ids whose ad is closed, for marks on applications. Reads the route's rows, or the stored rows while there is no answer. */
export function closedAdIds(rows) {
  return new Set((rows || []).filter(isClosedAd).map((row) => row.jobId))
}

export function formatSeen(value) {
  return value ? String(value).slice(0, 10) : ''
}
