import Badge from '../ui/Badge'
import { authorizationBadge } from '../../modules/jobs/workAuthorization'

/** The eligibility warning ("Outside your places", "Needs visa", ...), shown under the location. */
export default function AuthorizationBadge({ job }) {
  const badge = authorizationBadge(job)
  if (!badge) return null
  return <div className="mt-1"><span title={badge.reason}><Badge variant={badge.variant}>{badge.label}</Badge></span></div>
}
