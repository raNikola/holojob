/**
 * Display helpers for the salary a scorer parsed from an ad (job.salaryMonthlyEur,
 * EUR per month) and the flag it set against the candidate's minimum
 * (job.belowMinSalary). Labels and filters only; none of it is a score.
 */

/** A figure converted from USD or GBP carries "≈" and its source currency: it is not what the ad states. */
export function formatMonthlyEur(range) {
  if (!range) return ''
  const fmt = (n) => n.toLocaleString('en-US')
  const approx = range.converted ? '≈' : ''
  const amount = range.min === range.max ? `${fmt(range.min)}` : `${fmt(range.min)}–${fmt(range.max)}`
  return `${approx}€${amount}/month${range.converted && range.currency ? ` (from ${range.currency})` : ''}`
}

export function salaryBadges(job) {
  if (job?.belowMinSalary !== true) return []
  return [{ label: 'Below min salary', variant: 'medium', reason: `${formatMonthlyEur(job.salaryMonthlyEur)} is under your minimum` }]
}

function bound(value) {
  if (value === '' || value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * Filter on the parsed salary. A job whose pay could not be read always
 * passes: unknown is not below anything, and most ads state no pay.
 *
 * minSalary keeps jobs whose top figure reaches it; the desired range keeps
 * jobs whose range overlaps it.
 */
export function passesSalaryFilters(job, { minSalary = '', desiredMin = '', desiredMax = '' } = {}) {
  const pay = job?.salaryMonthlyEur
  if (!pay) return true
  const floor = bound(minSalary)
  if (floor != null && pay.max < floor) return false
  const lo = bound(desiredMin)
  const hi = bound(desiredMax)
  if (lo != null && pay.max < lo) return false
  if (hi != null && pay.min > hi) return false
  return true
}

/**
 * The filters with the profile's figures standing in for any salary filter the
 * user has not touched (null). An emptied field is '' and stays empty.
 */
export function withProfileSalaryDefaults(filters, basicProfile = {}) {
  const pick = (own, fromProfile) => (own === null || own === undefined ? (fromProfile ?? '') : own)
  const fromProfile = [filters.minSalary, filters.desiredSalaryMin, filters.desiredSalaryMax]
    .some((own, i) => (own === null || own === undefined) && [basicProfile.minSalaryEur, basicProfile.desiredSalaryMinEur, basicProfile.desiredSalaryMaxEur][i])
  return {
    ...filters,
    salaryFromProfile: Boolean(fromProfile),
    minSalary: pick(filters.minSalary, basicProfile.minSalaryEur),
    desiredSalaryMin: pick(filters.desiredSalaryMin, basicProfile.desiredSalaryMinEur),
    desiredSalaryMax: pick(filters.desiredSalaryMax, basicProfile.desiredSalaryMaxEur),
  }
}
