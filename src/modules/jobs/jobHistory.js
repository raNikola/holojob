/** Badges for a job's place in the discovery history: "Just found" (first seen recently, the `isNew` flag, not the triage status), or no longer listed. */
export function historyBadges(job) {
  const badges = []
  if (job?.isClosed) badges.push({ label: 'Closed', variant: 'low', reason: job.closedAt ? `No longer listed since ${job.closedAt.slice(0, 10)}` : '' })
  else if (job?.isNew) badges.push({ label: 'Just found', variant: 'high', reason: job.firstSeen ? `First seen ${job.firstSeen.slice(0, 10)}` : '' })
  return badges
}

/** A job that is still listed. Closed jobs stay visible, but are not candidates for "do something now" actions. */
export function isActionable(job) {
  return !job?.isClosed
}

export function formatSeen(value) {
  return value ? String(value).slice(0, 10) : ''
}
