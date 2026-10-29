import { MATCH_LABEL_VARIANT } from './matchScore'

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
