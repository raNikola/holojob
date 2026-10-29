import Badge from '../ui/Badge'
import {
  APPLY_VARIANT,
  PRIORITY_VARIANT,
} from '../../modules/jobs/matchScore'

export function PriorityBadge({ priority }) {
  if (!priority || priority === 'Reject') return null
  return <Badge variant={PRIORITY_VARIANT[priority] || 'default'}>{priority}</Badge>
}

export function ApplyBadge({ recommendation }) {
  if (!recommendation) return null
  return <Badge variant={APPLY_VARIANT[recommendation] || 'default'}>{recommendation}</Badge>
}
