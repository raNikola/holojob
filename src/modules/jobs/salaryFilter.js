/**
 * The Jobs salary filter: one range in EUR per month (From, To), parsed and checked here, matched
 * against `job.salaryMonthlyEur` ({ min, max } from python/job_scoring/salary.py, already in EUR per
 * month). No currency conversion happens in the browser. Pure.
 */

export const SALARY_PRESETS = [2000, 3000, 4000]
const MAX_DIGITS = 7

/** Keeps digits only: no decimals, letters or minus. Returns '' when nothing is left. */
export function sanitizeAmount(text) {
  return String(text ?? '').replace(/\D/g, '').slice(0, MAX_DIGITS)
}

/** A non-negative integer from typed text or a stored value, or null for empty / unreadable. */
export function parseAmount(value) {
  if (value === '' || value == null) return null
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null
  const digits = sanitizeAmount(value)
  return digits === '' ? null : Number(digits)
}

/** 3000 -> "3,000"; null -> "". */
export function formatAmount(n) {
  return n == null ? '' : n.toLocaleString('en-US')
}

/** True when From is above To. Either side empty is never an error. */
export function rangeError(from, to) {
  return from != null && to != null && from > to
}

export const RANGE_ERROR_TEXT = 'From must not be above To. The previous range stays active until this is fixed.'

/** One line under the control: "At least 3,000 / month", "Up to 4,000 / month", "2,000 to 4,000 / month", or '' for no range. */
export function describeRange(from, to) {
  if (from == null && to == null) return ''
  if (to == null) return `At least ${formatAmount(from)} / month`
  if (from == null) return `Up to ${formatAmount(to)} / month`
  return `${formatAmount(from)} to ${formatAmount(to)} / month`
}

/**
 * Does a job's pay match the range? A range of pay overlaps the filter range; a single figure
 * (min === max) is the same test, so it matches when it lies inside. No range matches everything.
 * A job with no readable pay follows `includeUnknown`.
 */
export function matchesSalary(pay, { from = null, to = null } = {}, includeUnknown = true) {
  if (from == null && to == null) return true
  if (!pay) return includeUnknown
  if (from != null && pay.max < from) return false
  if (to != null && pay.min > to) return false
  return true
}

/**
 * The three states of the salary filter, stored in `filters.salaryMode` (the only place they are named):
 * - 'untouched': never edited; the profile's figures apply when it has them (jobSalary.js);
 * - 'set': the owner typed a range (`salaryFrom` / `salaryTo`, '' = open end);
 * - 'cleared': the owner emptied it (x, Clear all, or deleting the numbers); stays empty, never refilled
 *   from the profile, also after a reload.
 */
export const SALARY_MODES = ['untouched', 'set', 'cleared']

/**
 * The mode of a saved filters object. A stored `salaryMode` wins. Older state has none: the current-shape
 * keys `salaryFrom` / `salaryTo` were written only by the owner's edits, so a figure means 'set' and a pair
 * of empties 'cleared'. The three-field panel's keys (minSalary, ...) with a figure mean 'set'; with only
 * empty strings or nulls they are NOT read as cleared (an emptied old field cannot be told from one that
 * was never typed in), so the state is 'untouched'.
 */
export function salaryModeOf(filters = {}) {
  if (SALARY_MODES.includes(filters.salaryMode)) return filters.salaryMode
  if (filters.salaryFrom != null || filters.salaryTo != null) {
    return parseAmount(filters.salaryFrom) != null || parseAmount(filters.salaryTo) != null ? 'set' : 'cleared'
  }
  const legacy = [filters.minSalary, filters.desiredSalaryMin, filters.desiredSalaryMax]
  return legacy.some((v) => parseAmount(v) != null) ? 'set' : 'untouched'
}

/**
 * The range a filters object stands for. Two shapes:
 * - current: `salaryFrom` / `salaryTo`;
 * - saved by the three-field panel: `minSalary` and `desiredSalaryMin` both mean "top figure reaches
 *   it", so together they are one From, the larger of the two (the same jobs pass as before), and
 *   `desiredSalaryMax` is To. Nothing is lost, only merged.
 */
export function salaryRangeOf(filters = {}) {
  if (filters.salaryMode === 'cleared') return { from: null, to: null }
  if (filters.salaryFrom != null || filters.salaryTo != null) {
    return { from: parseAmount(filters.salaryFrom), to: parseAmount(filters.salaryTo) }
  }
  const lows = [parseAmount(filters.minSalary), parseAmount(filters.desiredSalaryMin)].filter((n) => n != null)
  return { from: lows.length ? Math.max(...lows) : null, to: parseAmount(filters.desiredSalaryMax) }
}
