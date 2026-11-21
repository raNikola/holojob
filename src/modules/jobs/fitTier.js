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
