// Eligibility (python/job_scoring/eligibility.py): a state beside the score, never inside it. null = dormant (no authorized country in the profile).
export const ELIGIBILITY_LABELS = {
  authorized: 'Authorized',
  sponsorship_offered: 'Sponsorship offered',
  sponsorship_refused: 'Sponsorship refused',
  unknown: 'Unconfirmed',
}
const ELIGIBILITY_VARIANTS = { authorized: 'high', sponsorship_offered: 'high', sponsorship_refused: 'warn', unknown: 'medium' }

/** Hide-needs-visa filter: the ads whose eligibility is "Sponsorship refused". */
export const isBlockedByVisa = (job) => job?.eligibility?.state === 'sponsorship_refused'

const READ_BADGES = { insufficient_evidence: { label: 'Insufficient evidence', variant: 'medium' } }

/** Text badges for one row: eligibility, read status, and the location state. Each says why in its tooltip. */
export function eligibilityBadges(job) {
  const out = []
  const blockers = job?.blockedBy || []
  if (blockers.length) out.push({ label: 'Blocked', variant: 'warn', reason: blockers.map((b) => b.text).join('. ') })
  const eligibility = job?.eligibility
  if (eligibility?.state && ELIGIBILITY_LABELS[eligibility.state]) {
    out.push({ label: ELIGIBILITY_LABELS[eligibility.state], variant: ELIGIBILITY_VARIANTS[eligibility.state], reason: eligibility.reason || '' })
  }
  const read = READ_BADGES[job?.readStatus]
  if (read) out.push({ ...read, reason: (job.confidence?.reasons || []).join('. ') })
  if (job?.workAuthorization?.status === 'outside_allowed') {
    out.push({ label: 'Outside your places', variant: 'warn', reason: job.workAuthorization.reason || '' })
  } else if (job?.workAuthorization?.location?.flag) {
    // Remote or open to a region, but the ad never says where you may live: a flag, not a cap.
    out.push({ label: job.workAuthorization.location.flag, variant: 'medium', reason: job.workAuthorization.location.reason || '' })
  }
  return out
}

export const isCapReason = (reason) => reason.startsWith('Capped:')
