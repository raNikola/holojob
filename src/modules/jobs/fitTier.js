// Coarse fit tiers of the Jobs list (owner decision 2026-11-21, option A). Derived from scoring 1.6 output, nothing is scored here.
//
// Experiment B did not beat scoring 1.6 (docs/DECISIONS.md, "Jobs list: three coarse tiers"), and no within-tier ordering is proven.
// So the list shows three tiers and makes no claim about the order inside one. The tiers reuse the boundaries that already exist:
//   Strong fit   = the Apply line, Fit Score 70+ (labels.py APPLY_MIN_SCORE; bands Excellent + Strong), verdict not Skip
//   Possible fit = Fit Score 55 to 69 (band Good, labels.py match_label)
//   Weak fit     = below 55 (bands Weak + Reject), or an Avoid-role / avoided-industry Skip verdict at any score
// Role class "other" is capped at 54 by ceilings.py, so it can only land in Weak fit. A blocking fact (work authorization, location,
// language, explicit barrier: `blockedBy`) is never in a tier: the row stays in its own Blocked group.

import { fitScoreOf, isNotRead } from './matchScore.js'
import { isClosedAd } from './jobHistory.js'

export const TIER_STRONG = 'strong'
export const TIER_POSSIBLE = 'possible'
export const TIER_WEAK = 'weak'

/** The tiers, best first. */
export const TIERS = [
  { id: TIER_STRONG, label: 'Strong fit' },
  { id: TIER_POSSIBLE, label: 'Possible fit' },
  { id: TIER_WEAK, label: 'Weak fit' },
]

/** Shown in a tier heading: the order inside a tier is not a ranking by fit. */
export const TIER_ORDER_NOTE = 'Not ranked by fit; remote-feasible from Serbia first, then newest'

const INDEX = Object.fromEntries(TIERS.map((tier, i) => [tier.id, i]))

export const isBlockedRow = (row) => (row?.blockedBy || []).length > 0 || row?.applyRecommendation === 'Blocked'

/** The tier of a rated, unblocked ad, or null when the row has no Fit Score or is blocked (those are not in a tier). */
export function tierOf(row) {
  if (isBlockedRow(row)) return null
  const score = fitScoreOf(row)
  if (score === null) return null
  if (row.applyRecommendation === 'Skip') return TIER_WEAK
  return score >= 70 ? TIER_STRONG : score >= 55 ? TIER_POSSIBLE : TIER_WEAK
}

/** 0 for Strong fit, 1 Possible, 2 Weak; null for a row in no tier. */
export const tierIndexOf = (row) => {
  const tier = tierOf(row)
  return tier === null ? null : INDEX[tier]
}

/** The label of a row's tier, or null. */
export const tierLabelOf = (row) => TIERS[tierIndexOf(row)]?.label ?? null

/**
 * The group a row sits in under the default order, which is also the heading above it: not read, closed, blocked, one of the tiers,
 * or not scored. The default order puts those groups in this sequence (`notReadFirst`, `closedLast`, `blockedLast`).
 */
export function listGroupOf(row) {
  if (isNotRead(row)) return 'notRead'
  if (isClosedAd(row)) return 'closed'
  if (isBlockedRow(row)) return 'blocked'
  return tierOf(row) ?? 'unscored'
}

const GROUP_HEADING = {
  notRead: 'Not read: the description is empty or unreadable, so there is no Fit Score',
  closed: 'Closed or no longer on the board',
  blocked: 'Blocked: a hard rule fails (work authorization, location, language or an explicit barrier)',
  unscored: 'Not scored',
  ...Object.fromEntries(TIERS.map((tier) => [tier.id, `${tier.label} (${TIER_ORDER_NOTE})`])),
}

/** The heading above row `index` in the default order: the group's heading where the group starts, else null. */
export function groupHeading(rows, index) {
  const group = listGroupOf(rows[index])
  if (index > 0 && listGroupOf(rows[index - 1]) === group) return null
  return GROUP_HEADING[group]
}

/**
 * "Engine not run" (owner decision 2026-11-21): the unmet-requirements ceiling (`ceilings.py`, caps 70+ at 69) only runs for an ad with
 * a current engine answer; `engineCoverage.status` is `not_evaluated` for an ad without one. Such an ad is not capped, so a Strong fit
 * placement is provisional until the engine has run. A Possible or Weak placement cannot be lowered by that ceiling, so only Strong is marked.
 */
export const ENGINE_NOT_RUN_LABEL = 'Engine not run'
export const ENGINE_NOT_RUN_NOTE = 'Engine not run: this placement is provisional until the evidence engine has run for this ad. Its unmet-requirements check can still lower it to Possible fit.'

export const isProvisionalTier = (row) => tierOf(row) === TIER_STRONG && row?.engineCoverage?.status === 'not_evaluated'

/**
 * "Many unknown musts" (owner decision 2026-11-23, display only): among the MUST requirements of a current engine answer, the count with status
 * UNKNOWN or NOT_EVIDENCED; the label shows at 30% or more of the musts. Preferred requirements and the language gate are not counted.
 * Tier, score and order never read this. Returns { unknown, total } or null without an engine answer or without musts.
 */
export const MANY_UNKNOWN_MUSTS_PERCENT = 30

export function unknownMustCounts(row) {
  const shadow = row?.engineShadow
  if (!shadow || shadow.error || !Array.isArray(shadow.requirements)) return null
  const musts = shadow.requirements.filter((r) => r?.importance === 'must')
  if (musts.length === 0) return null
  const unknown = musts.filter((r) => r.status === 'UNKNOWN' || r.status === 'NOT_EVIDENCED').length
  return { unknown, total: musts.length }
}

/** The label text ("4 of 9 musts unknown") or null when the row is under the threshold or has no engine answer. */
export function manyUnknownMustsLabel(row) {
  const counts = unknownMustCounts(row)
  if (!counts || counts.unknown * 100 < MANY_UNKNOWN_MUSTS_PERCENT * counts.total) return null
  return `${counts.unknown} of ${counts.total} musts unknown`
}

/**
 * "Ad not read: sponsorship and language not checked" (owner decision 2026-11-23, display only): a row scored without the ad's extracted facts
 * (`aiEnrichment: 'missing'`, set by run_scoring) has had no sponsorship or language check, so no Blocked flag from those can apply yet.
 * Same style as "N of M musts unknown"; it changes no tier, score or order. Null for a row whose ad was read.
 */
export const AD_NOT_READ_LABEL = 'Ad not read: sponsorship and language not checked'
export const adNotReadLabel = (row) => (row?.aiEnrichment === 'missing' ? AD_NOT_READ_LABEL : null)

/** How many of `rows` are in each tier (`{ strong, possible, weak }`); `include` leaves rows out, for example closed ads. */
export function tierCounts(rows, include = () => true) {
  const counts = { strong: 0, possible: 0, weak: 0 }
  for (const row of rows || []) {
    const tier = include(row) ? tierOf(row) : null
    if (tier !== null) counts[tier] += 1
  }
  return counts
}
