import Badge from '../ui/Badge'
import { ENGINE_NOT_RUN_LABEL, ENGINE_NOT_RUN_NOTE, TIER_ORDER_NOTE, TIER_STRONG, TIER_POSSIBLE, isBlockedRow, isProvisionalTier, manyUnknownMustsLabel, tierOf, tierLabelOf } from '../../modules/jobs/fitTier'
import { INSUFFICIENT_LABEL, NOT_READ_LABEL, isInsufficientData } from '../../modules/jobs/matchScore'

const VARIANT = { [TIER_STRONG]: 'high', [TIER_POSSIBLE]: 'medium' }

/**
 * The fit cell of the Jobs list and the resume list: the coarse tier, never the number or the band name (owner decision 2026-11-21).
 * The Fit Score stays on the ad's detail view. A blocked ad shows "Blocked", an unread one "Not read", and an ad with no score "Not scored".
 * A Strong fit the engine has not evaluated carries an "Engine not run" marker: the placement is provisional.
 */
export default function FitTier({ job }) {
  if (isBlockedRow(job)) return <Badge variant="warn">Blocked</Badge>
  if (isInsufficientData(job)) {
    const label = job?.matchLabel === INSUFFICIENT_LABEL ? INSUFFICIENT_LABEL : NOT_READ_LABEL
    return <span title={(job.insufficientReasons || []).join('. ') || undefined}><Badge variant="medium">{label}</Badge></span>
  }
  const tier = tierOf(job)
  if (tier === null) return <span className="text-stone-400">Not scored</span>
  const provisional = isProvisionalTier(job)
  // Informational, next to the Engine not run chip: shown on Strong rows only; the detail page shows it for every tier.
  const unknownMusts = tier === TIER_STRONG ? manyUnknownMustsLabel(job) : null
  return (
    <span className="inline-flex flex-wrap items-center gap-1" title={provisional ? `${ENGINE_NOT_RUN_NOTE} ${TIER_ORDER_NOTE}.` : `Tier: ${TIER_ORDER_NOTE}`}>
      <Badge variant={VARIANT[tier] || 'low'}>{tierLabelOf(job)}</Badge>
      {provisional && <Badge variant="default">{ENGINE_NOT_RUN_LABEL}</Badge>}
      {unknownMusts && <Badge variant="default">{unknownMusts}</Badge>}
    </span>
  )
}
