import { matchesSalary, salaryModeOf, salaryRangeOf } from './salaryFilter.js'

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
 * user has not touched. The three states (untouched / set / cleared) are defined in salaryFilter.js.
 */
export function withProfileSalaryDefaults(filters, profile) {
  const basicProfile = profile || {}
  const pick = (own, fromProfile) => (own === null || own === undefined ? (fromProfile ?? '') : own)
  const mode = salaryModeOf(filters)
  if (mode === 'cleared') {
    return { ...filters, salaryMode: 'cleared', salaryFromProfile: false, salaryFrom: '', salaryTo: '' }
  }
  if (mode === 'set' && (filters.salaryFrom != null || filters.salaryTo != null)) {
    return { ...filters, salaryMode: 'set', salaryFromProfile: false, salaryFrom: filters.salaryFrom ?? '', salaryTo: filters.salaryTo ?? '' }
  }
  // 'untouched' takes the profile's figures; 'set' by the three-field panel keeps every field it saved
  // and fills only the ones it left null.
  const legacy = mode === 'set' ? [filters.minSalary, filters.desiredSalaryMin, filters.desiredSalaryMax] : [null, null, null]
  const [min, desiredMin, desiredMax] = legacy
  const fromProfile = [min, desiredMin, desiredMax]
    .some((own, i) => (own === null || own === undefined) && [basicProfile.minSalaryEur, basicProfile.desiredSalaryMinEur, basicProfile.desiredSalaryMaxEur][i])
  return {
    ...filters,
    salaryMode: mode,
    salaryFromProfile: Boolean(fromProfile),
    minSalary: pick(min, basicProfile.minSalaryEur),
    desiredSalaryMin: pick(desiredMin, basicProfile.desiredSalaryMinEur),
    desiredSalaryMax: pick(desiredMax, basicProfile.desiredSalaryMaxEur),
    salaryFrom: undefined,
    salaryTo: undefined,
  }
}
