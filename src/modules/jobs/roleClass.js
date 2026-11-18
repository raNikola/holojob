/**
 * The role class of an ad (Fit 3, stored classification of the ad's responsibilities), stamped on each scored row as `roleClass` by
 * python/job_scoring/run_scoring.py. A badge and a filter only: it never enters the score, the label, the priority or the order.
 * A row without the field (a hand-entered job, a file from before the stamp) reads as "not available".
 */
export const ROLE_CLASS_OPTIONS = ['target', 'adjacent', 'other', 'not available']

const LABELS = { target: 'Target role', adjacent: 'Adjacent role', other: 'Other role', 'not available': 'Role not available' }
const VARIANTS = { target: 'high', adjacent: 'medium', other: 'low', 'not available': 'default' }
const REASONS = {
  target: 'The ad\'s responsibilities describe one of your target roles.',
  adjacent: 'The ad\'s responsibilities describe a role adjacent to your target roles.',
  other: 'The ad\'s responsibilities describe a different function.',
  'not available': 'No role class: the ad has no text, was not classified, or the role could not be confirmed from the ad.',
}

export const roleClassOf = (job) => (ROLE_CLASS_OPTIONS.includes(job?.roleClass) ? job.roleClass : 'not available')
export const roleClassLabel = (value) => LABELS[value] || LABELS['not available']
export const roleClassBadge = (job) => {
  const value = roleClassOf(job)
  return { value, label: LABELS[value], variant: VARIANTS[value], reason: job?.roleName ? `${REASONS[value]} (${job.roleName})` : REASONS[value] }
}
/** The Role class select's options: `{ value, label }`. */
export const ROLE_CLASS_SELECT = ROLE_CLASS_OPTIONS.map((value) => ({ value, label: LABELS[value] }))
