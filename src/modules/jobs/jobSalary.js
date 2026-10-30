import { matchesSalary, parseAmount, salaryRangeOf } from './salaryFilter.js'

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

/**
 * Filter on the parsed salary (salaryFilter.js). A job whose pay could not be read passes: unknown is
 * not below anything, and most ads state no pay.
 *
 * minSalary keeps jobs whose top figure reaches it; the desired range keeps
 * jobs whose range overlaps it.
 */
export function passesSalaryFilters(job, { minSalary = '', desiredMin = '', desiredMax = '' } = {}) {
  return matchesSalary(job?.salaryMonthlyEur, salaryRangeOf({ minSalary, desiredSalaryMin: desiredMin, desiredSalaryMax: desiredMax }), true)
}

/**
 * The filters with the profile's figures standing in for any salary filter the
 * user has not touched (null). In the current shape an emptied range ('') stays empty; in the old
 * three-field shape a state with no figure at all counts as untouched.
 */
export function withProfileSalaryDefaults(filters, basicProfile = {}) {
  const pick = (own, fromProfile) => (own === null || own === undefined ? (fromProfile ?? '') : own)
  if (filters.salaryFrom != null || filters.salaryTo != null) {
    // The current shape: From stands in for the profile's larger lower figure, To for its desired maximum.
    const lows = [basicProfile.minSalaryEur, basicProfile.desiredSalaryMinEur].map(parseAmount).filter((n) => n != null)
    const profileFrom = lows.length ? Math.max(...lows) : ''
    const profileTo = basicProfile.desiredSalaryMaxEur ?? ''
    return {
      ...filters,
      salaryFromProfile: (filters.salaryFrom == null && profileFrom !== '') || (filters.salaryTo == null && profileTo !== ''),
      salaryFrom: pick(filters.salaryFrom, profileFrom),
      salaryTo: pick(filters.salaryTo, profileTo),
    }
  }
  // Saved by the three-field panel with no figure in any field: nothing was chosen (an emptied field is
  // not a figure), so the profile's figures apply. Any figure present keeps every field as saved.
  const legacy = [filters.minSalary, filters.desiredSalaryMin, filters.desiredSalaryMax]
  const [min, desiredMin, desiredMax] = legacy.some((v) => parseAmount(v) != null) ? legacy : [null, null, null]
  const fromProfile = [min, desiredMin, desiredMax]
    .some((own, i) => (own === null || own === undefined) && [basicProfile.minSalaryEur, basicProfile.desiredSalaryMinEur, basicProfile.desiredSalaryMaxEur][i])
  return {
    ...filters,
    salaryFromProfile: Boolean(fromProfile),
    minSalary: pick(min, basicProfile.minSalaryEur),
    desiredSalaryMin: pick(desiredMin, basicProfile.desiredSalaryMinEur),
    desiredSalaryMax: pick(desiredMax, basicProfile.desiredSalaryMaxEur),
  }
}
