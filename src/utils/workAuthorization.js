/**
 * Where the candidate may legally work, where they will take a job, and
 * whether they would move: basicProfile.workAuthorization, .allowedLocations
 * and .relocation.
 *
 * Every value is the candidate's own. Nothing defaults to a place: no work
 * rights means the visa is not checked, and an empty allowedLocations gates
 * nothing. Codes are ISO country codes or the region codes in
 * src/data/geography.json, which the form uses for its options. This file
 * imports no JSON, so plain Node can load it (scripts/regenerate-intelligence.js).
 */

export const AUTHORIZATION_BASES = ['citizen', 'permanent_resident', 'work_permit', 'other']

/** none: only the candidate's own cities. abroad: another country, not their own. anywhere: any place. */
export const RELOCATION_OPTIONS = ['none', 'abroad', 'anywhere']

export const REMOTE = 'REMOTE'

const code = (value) => (typeof value === 'string' ? value.trim().toUpperCase() : '')

/**
 * @param {unknown} value
 * @returns {{ holds: { jurisdiction: string, basis: string }[], openToSponsorship: boolean }}
 */
export function normalizeWorkAuthorization(value) {
  const holds = Array.isArray(value?.holds) ? value.holds : []
  return {
    holds: holds
      .map((entry) => ({
        jurisdiction: code(entry?.jurisdiction),
        basis: AUTHORIZATION_BASES.includes(entry?.basis) ? entry.basis : '',
      }))
      .filter((entry) => entry.jurisdiction),
    openToSponsorship: value?.openToSponsorship === true,
  }
}

/**
 * @param {unknown} value
 * @returns {string[]}
 */
export function normalizeAllowedLocations(value) {
  if (!Array.isArray(value)) return []
  return [...new Set(value.map(code).filter(Boolean))]
}

/**
 * @param {unknown} value
 * @returns {'none' | 'abroad' | 'anywhere'}
 */
export function normalizeRelocation(value) {
  return RELOCATION_OPTIONS.includes(value) ? value : 'none'
}
