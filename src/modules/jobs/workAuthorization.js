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
  // Step 2c: a required language the ad may ask for but that was not confirmed (no quote in the ad, or no declared language list). A flag, never Blocked.
  const unconfirmed = job?.languageState?.unconfirmed || []
  if (unconfirmed.length) out.push({ label: 'Language unconfirmed', variant: 'medium', reason: unconfirmed.map((u) => u.language).join(', ') })
  const eligibility = job?.eligibility
  if (eligibility?.state && ELIGIBILITY_LABELS[eligibility.state]) {
    out.push({ label: ELIGIBILITY_LABELS[eligibility.state], variant: ELIGIBILITY_VARIANTS[eligibility.state], reason: eligibility.reason || '' })
  }
  const feasibility = feasibilityOf(job)
  if (feasibility) out.push({ ...FEASIBILITY_BADGES[feasibility.code], reason: feasibility.why })
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

const norm = (value) => (typeof value === 'string' ? value.trim().toLowerCase() : '')

/** The board's own work mode first, the extracted one where the board left it unset ("unclear" is unknown), as location_match.job_work_mode. */
function workModeOf(job) {
  const board = norm(job?.workMode).replace(/[ -]/g, '_')
  if (board && board !== 'unclear' && board !== 'unknown') return board === 'on_site' ? 'onsite' : board
  const extracted = norm(job?.llmFacts?.workMode)
  return extracted === 'unclear' || extracted === 'unknown' ? '' : extracted
}

// Clear remote wording in the ad's own text (fix 4 of scoring 1.6; python/job_scoring/remote_text.py holds the same list): it wins over a structured field
// that says onsite or hybrid, because the structured field is a board default or a guess and the sentence is the ad. A negation just before it cancels it.
const CLEAR_REMOTE = [
  /\b(?:fully|100%|entirely|completely)[ -]remote\b/,
  /\bwork(?:ing)?\s+(?:remotely\s+)?from\s+anywhere\b/,
  /\bremote\s+from\s+anywhere\b/,
]
const REMOTE_NEGATION = /\b(?:not|no|never|isn't|aren't|non|without)\b[^.;\n]{0,25}$/

/** The phrase of the ad text that says the job is fully remote, or null. Tags and case are ignored. */
export function clearRemoteText(description) {
  const text = String(description || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/\u2019/g, "'").toLowerCase()
  for (const pattern of CLEAR_REMOTE) {
    for (const m of text.matchAll(new RegExp(pattern.source, 'g'))) {
      if (!REMOTE_NEGATION.test(text.slice(Math.max(0, m.index - 30), m.index))) return m[0]
    }
  }
  return null
}

// A remote ad that names no country, or names the world, Europe or Serbia, can be done from Serbia. "EU" does not: Serbia is not in it.
const REMOTE_OPEN = new Set(['WORLDWIDE', 'EUROPE', 'RS'])
const SERBIA = 'RS'

/**
 * The part of "Unconfirmed" that tells an ad the candidate can plausibly take from one that needs a work permit (owner decision 2026-11-18). Display and
 * list order only: it reads existing fields (remote eligibility, job country, the B2B / employer-of-record exception) and changes no score, band or
 * verdict. null for every state but Unconfirmed.
 * @returns {{ code: 'remote_feasible' | 'onsite_needs_authorization', why: string } | null}
 */
function feasibilityOf(job) {
  const eligibility = job?.eligibility
  if (eligibility?.state !== 'unknown') return null
  if (eligibility.b2b === true) return { code: 'remote_feasible', why: 'The ad also accepts B2B or contractor work.' }
  const facts = job?.llmFacts || {}
  if (String(facts.jobCountry || '').toUpperCase() === SERBIA) return { code: 'remote_feasible', why: 'The job is in Serbia.' }
  if (job?.isRemote === true || workModeOf(job) === 'remote' || clearRemoteText(job?.description)) {
    const allowed = (Array.isArray(facts.remoteEligibility) ? facts.remoteEligibility : []).map((c) => String(c).trim().toUpperCase()).filter(Boolean)
    if (!allowed.length) return { code: 'remote_feasible', why: 'Remote, and the ad names no country restriction.' }
    if (allowed.some((c) => REMOTE_OPEN.has(c))) return { code: 'remote_feasible', why: `Remote, open to ${allowed.join(', ')}.` }
    return { code: 'onsite_needs_authorization', why: `Remote, but limited to ${allowed.join(', ')}, which does not include Serbia.` }
  }
  return { code: 'onsite_needs_authorization', why: 'Not remote: an office job outside Serbia needs a work permit the ad does not promise.' }
}

export const eligibilityFeasibility = (job) => feasibilityOf(job)?.code ?? null

const FEASIBILITY_BADGES = {
  remote_feasible: { label: 'Remote-feasible', variant: 'high' },
  onsite_needs_authorization: { label: 'Onsite, authorization needed', variant: 'warn' },
}

/** For the list order: the ad can be taken from Serbia as it stands (authorized, sponsored, or an Unconfirmed ad that is remote-feasible). */
export function isRemoteFeasible(job) {
  const state = job?.eligibility?.state
  return state === 'authorized' || state === 'sponsorship_offered' || feasibilityOf(job)?.code === 'remote_feasible'
}

export const isCapReason = (reason) => reason.startsWith('Capped:')
