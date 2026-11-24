// The filters a list request may carry (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P3 S3): the Jobs screen's own filters and the salary range keys, each with the type
// it must have. One list for the browser (what it picks to send) and the server (what it accepts), so a new filter is added in one place.
import { DEFAULT_FILTERS } from './jobStorage.js'

export const FILTER_TYPES = {
  ...Object.fromEntries(Object.entries(DEFAULT_FILTERS).map(([key, value]) => [key, Array.isArray(value) ? 'strings' : typeof value])),
  minScore: 'numberOrString', salaryFrom: 'numberOrString', salaryTo: 'numberOrString',
  minSalary: 'numberOrNull', desiredSalaryMin: 'numberOrNull', desiredSalaryMax: 'numberOrNull',
}

/** Whether `value` has the type `kind` names. */
export function filterValueOk(kind, value) {
  if (kind === 'strings') return Array.isArray(value) && value.every((v) => typeof v === 'string')
  if (kind === 'numberOrString') return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))
  if (kind === 'numberOrNull') return value === null || (typeof value === 'number' && Number.isFinite(value))
  return kind !== undefined && typeof value === kind
}

/** The filters of a list request: the keys the list knows, with a value of the right type. Anything else on the object (UI state) is left out. */
export function pickFilters(filters) {
  return Object.fromEntries(Object.entries(filters ?? {}).filter(([key, value]) => Object.hasOwn(FILTER_TYPES, key) && value !== undefined && filterValueOk(FILTER_TYPES[key], value)))
}
