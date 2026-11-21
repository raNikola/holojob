import Badge from '../ui/Badge'
import { TIER_ORDER_NOTE, TIER_STRONG, TIER_POSSIBLE, isBlockedRow, tierOf, tierLabelOf } from '../../modules/jobs/fitTier'
import { INSUFFICIENT_LABEL, NOT_READ_LABEL, isInsufficientData } from '../../modules/jobs/matchScore'

const VARIANT = { [TIER_STRONG]: 'high', [TIER_POSSIBLE]: 'medium' }

/**
 * The fit cell of the Jobs list: the coarse tier, never the number or the band name (owner decision 2026-11-21). The Fit Score stays on
 * the ad's detail view. A blocked ad shows "Blocked", an unread one "Not read", and an ad with no score "Not scored".
 */
export default function FitTier({ job }) {
  if (isBlockedRow(job)) return <Badge variant="warn">Blocked</Badge>
  if (isInsufficientData(job)) {
    const label = job?.matchLabel === INSUFFICIENT_LABEL ? INSUFFICIENT_LABEL : NOT_READ_LABEL
    return <span title={(job.insufficientReasons || []).join('. ') || undefined}><Badge variant="medium">{label}</Badge></span>
  }
  const tier = tierOf(job)
  if (tier === null) return <span className="text-stone-400">Not scored</span>
  return <span title={`Tier: ${TIER_ORDER_NOTE}`}><Badge variant={VARIANT[tier] || 'low'}>{tierLabelOf(job)}</Badge></span>
}
