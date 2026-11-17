import Badge from '../ui/Badge'
import { eligibilityBadges } from '../../modules/jobs/workAuthorization'

/** The eligibility state, the read status and the location flag ("Unconfirmed", "Insufficient evidence", "Outside your places", ...), as text badges under the location. */
export default function AuthorizationBadge({ job }) {
  const badges = eligibilityBadges(job)
  if (!badges.length) return null
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {badges.map((badge) => <span key={badge.label} title={badge.reason}><Badge variant={badge.variant}>{badge.label}</Badge></span>)}
    </div>
  )
}
