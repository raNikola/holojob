/** Badges for a job's place in the discovery history: first seen recently, or no longer listed. */
export function historyBadges(job) {
  const badges = []
  if (job?.isClosed) badges.push({ label: 'Closed', variant: 'low', reason: job.closedAt ? `No longer listed since ${job.closedAt.slice(0, 10)}` : '' })
  else if (job?.isNew) badges.push({ label: 'New', variant: 'high', reason: job.firstSeen ? `First seen ${job.firstSeen.slice(0, 10)}` : '' })
  return badges
}

export function formatSeen(value) {
  return value ? String(value).slice(0, 10) : ''
}
