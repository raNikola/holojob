export const MATCH_LABELS = ['Excellent', 'Strong', 'Good', 'Weak', 'Reject', 'Insufficient data']
export const PRIORITIES = ['P1', 'P2', 'P3', 'Reject']
export const APPLY_RECOMMENDATIONS = ['Apply', 'Maybe', 'Skip']

export const MATCH_LABEL_VARIANT = {
  Excellent: 'high',
  Strong: 'high',
  Good: 'medium',
  Weak: 'low',
  Reject: 'default',
  'Insufficient data': 'medium',
}

export const PRIORITY_VARIANT = {
  P1: 'high',
  P2: 'medium',
  P3: 'low',
  Reject: 'default',
}

export const APPLY_VARIANT = {
  Apply: 'high',
  Maybe: 'medium',
  Skip: 'low',
}

/**
 * "Insufficient data" is a state, not a band (python/job_scoring/data_sufficiency.py): the ad says too little to score.
 * The record still carries a number (at most 5) for older readers, which must never be read as a Fit Score.
 */
export const INSUFFICIENT_LABEL = 'Insufficient data'
export const INSUFFICIENT_PRIORITY = 'Unrated'
export const INSUFFICIENT_APPLY = 'Not assessed'

export function isInsufficientData(job) {
  return job?.dataStatus === 'insufficient' || job?.matchLabel === INSUFFICIENT_LABEL
}

/** The Fit Score as a number, or null when there is none (unscored, or insufficient data). Sort, filter and averages read this. */
export function fitScoreOf(job) {
  if (isInsufficientData(job) || typeof job?.matchScore !== 'number') return null
  return job.matchScore
}

/**
 * The score the row would have with no cap applied (scorer.py `scoreBeforeCaps`), or the Fit Score for a row scored before the field
 * existed. It only breaks ties in the default Jobs order; it is never shown and decides no label or priority.
 */
export function preCapScoreOf(job) {
  const fit = fitScoreOf(job)
  if (fit === null) return null
  return typeof job.scoreBeforeCaps === 'number' ? job.scoreBeforeCaps : fit
}

export function hasMatchScores(jobs) {
  return (jobs || []).some((j) => typeof j.matchScore === 'number' || isInsufficientData(j))
}

export function formatMatchScore(job) {
  return fitScoreOf(job)
}
