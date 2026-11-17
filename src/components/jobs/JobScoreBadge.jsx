import Badge from '../ui/Badge'
import {
  APPLY_VARIANT,
  BLOCKED,
  INSUFFICIENT_APPLY,
  INSUFFICIENT_PRIORITY,
  PRIORITY_VARIANT,
} from '../../modules/jobs/matchScore'

export function PriorityBadge({ priority }) {
  if (!priority || priority === 'Reject' || priority === INSUFFICIENT_PRIORITY || priority === BLOCKED) return null
  return <Badge variant={PRIORITY_VARIANT[priority] || 'default'}>{priority}</Badge>
}

export function ApplyBadge({ recommendation }) {
  if (!recommendation || recommendation === INSUFFICIENT_APPLY || recommendation === BLOCKED) return null
  return <Badge variant={APPLY_VARIANT[recommendation] || 'default'}>{recommendation}</Badge>
}
