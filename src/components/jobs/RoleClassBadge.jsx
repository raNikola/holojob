import Badge from '../ui/Badge'
import { roleClassBadge } from '../../modules/jobs/roleClass'

/** The role class of the ad (target / adjacent / other / not available). Display only; it does not change the score or the order. */
export default function RoleClassBadge({ job }) {
  const badge = roleClassBadge(job)
  return <span title={badge.reason}><Badge variant={badge.variant}>{badge.label}</Badge></span>
}
