/**
 * Salary expectations in the profile, in EUR per month. Display only: they feed
 * a badge and two filters, and never the match score.
 *
 * basicProfile.minSalaryEur, .desiredSalaryMinEur, .desiredSalaryMaxEur
 * Each is a positive number or null; anything else reads as not set.
 */

export function normalizeSalaryEur(value) {
  if (value === '' || value == null) return null
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null
}

/** The three fields as stored on basicProfile, normalised. */
export function normalizeSalaryTargets(bp = {}) {
  return {
    minSalaryEur: normalizeSalaryEur(bp.minSalaryEur),
    desiredSalaryMinEur: normalizeSalaryEur(bp.desiredSalaryMinEur),
    desiredSalaryMaxEur: normalizeSalaryEur(bp.desiredSalaryMaxEur),
  }
}

/** The shape jobFitPreferences carries for scoring: { minSalaryEur, desiredSalaryEur: { min, max } }. */
export function salaryPreferences(bp = {}) {
  const t = normalizeSalaryTargets(bp)
  return {
    minSalaryEur: t.minSalaryEur,
    desiredSalaryEur: { min: t.desiredSalaryMinEur, max: t.desiredSalaryMaxEur },
  }
}
