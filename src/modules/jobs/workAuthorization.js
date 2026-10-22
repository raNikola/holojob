export const NEEDS_VISA_STATUSES = new Set(['needs_visa_refused', 'needs_visa_silent'])

const BADGES = {
  needs_visa_refused: { label: 'No visa', variant: 'warn' },
  needs_visa_silent: { label: 'Needs visa', variant: 'medium' },
  outside_allowed: { label: 'Outside your places', variant: 'warn' },
  sponsored: { label: 'Sponsored', variant: 'high' },
}

export function authorizationBadge(job) {
  const badge = BADGES[job?.workAuthorization?.status]
  return badge ? { ...badge, reason: job.workAuthorization.reason || '' } : null
}

export const isCapReason = (reason) => reason.startsWith('Capped:')
