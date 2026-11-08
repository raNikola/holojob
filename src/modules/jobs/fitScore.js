import { APPLY_VARIANT, INSUFFICIENT_APPLY, INSUFFICIENT_PRIORITY, MATCH_LABEL_VARIANT, PRIORITY_VARIANT } from './matchScore'

/**
 * Band to style for the Fit Score display. The bands themselves (names and thresholds) are decided by
 * `match_label` in python/job_scoring/labels.py and arrive as `job.matchLabel`; the label-to-variant map is
 * MATCH_LABEL_VARIANT. This adds only the number's colour per variant, so there is one band implementation.
 */
const SCORE_TEXT = {
  high: 'text-emerald-700 dark:text-emerald-300',
  medium: 'text-amber-700 dark:text-amber-300',
  low: 'text-stone-500 dark:text-stone-400',
  warn: 'text-red-700 dark:text-red-300',
  default: 'text-stone-900 dark:text-stone-100',
}

export function fitScoreStyle(label) {
  const variant = MATCH_LABEL_VARIANT[label] || 'default'
  return { variant, scoreClass: SCORE_TEXT[variant] }
}

/** The chips that follow the score on one row, in order: priority (never `Reject`), then the apply recommendation. */
export function scoreRowChips(job) {
  const chips = []
  if (job?.priority && job.priority !== 'Reject' && job.priority !== INSUFFICIENT_PRIORITY) chips.push({ kind: 'priority', text: job.priority, variant: PRIORITY_VARIANT[job.priority] || 'default' })
  if (job?.applyRecommendation && job.applyRecommendation !== INSUFFICIENT_APPLY) chips.push({ kind: 'apply', text: job.applyRecommendation, variant: APPLY_VARIANT[job.applyRecommendation] || 'default' })
  return chips
}
