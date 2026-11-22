/**
 * Save guard (owner decision 2026-11-23, after the overwrite of 2026-11-21 02:12).
 *
 * The browser pushes its whole profile or intelligence to the server (routes /api/profile/save and /api/intelligence/save, the pipeline
 * run, the re-scrape). A browser with an empty profile therefore replaced a populated server file. This refuses such a save:
 *
 *   a payload is refused when it would EMPTY, or CUT BY MORE THAN HALF (lists of 3 or more), at least GUARD_LOSS_LIMIT of the
 *   owner-set preference fields below that are filled in on the server.
 *
 * Why a count and not a diff of "edited fields": the payload carries no list of what the user edited (`_editedFields` is stripped on
 * export). One edit, or clearing one or two fields, passes; a fresh browser that has none of the owner's settings loses many at once.
 * A server file that does not exist, cannot be read or has nothing filled in has nothing to lose, so a first save always passes.
 * There is no override: to change many settings, save in smaller steps. Writes by scripts (restore, import, re-score) do not pass here.
 *
 * Logs the refusal with the field NAMES only; never a value. Own proposal (no benchmark guards a save: see docs/DECISIONS.md).
 */

import fs from 'node:fs'

export const GUARD_LOSS_LIMIT = 3

const PROFILE_FIELDS = [
  'basicProfile.targetRoles', 'basicProfile.allowedLocations', 'basicProfile.preferredLocations', 'basicProfile.languages',
  'basicProfile.remotePreference', 'basicProfile.roleFamily', 'basicProfile.minSalaryEur', 'basicProfile.desiredSalaryMinEur',
  'basicProfile.desiredSalaryMaxEur', 'basicProfile.salaryExpectation', 'basicProfile.workAuthorization.holds',
  'questionnaire.answers', 'repositories.githubLinks', 'cvLibrary',
]

const INTELLIGENCE_FIELDS = [
  'languages', 'roleFamily',
  'roleStrategy.primaryTargetRoles', 'roleStrategy.secondaryTargetRoles', 'roleStrategy.stretchRoles', 'roleStrategy.avoidRoles', 'roleStrategy.searchRoleVariants',
  'searchStrategy.jobSpySearchTerms', 'searchStrategy.linkedinSearchQueries', 'searchStrategy.recommendedSearchQueries', 'searchStrategy.locationFilters',
  'jobFitPreferences.allowedLocations', 'jobFitPreferences.preferredLocations', 'jobFitPreferences.preferredIndustries', 'jobFitPreferences.avoidedIndustries',
  'jobFitPreferences.preferredCompanyTypes', 'jobFitPreferences.workToAvoid', 'jobFitPreferences.remotePreference', 'jobFitPreferences.salaryExpectation',
  'jobFitPreferences.minSalaryEur', 'jobFitPreferences.desiredSalaryEur.min', 'jobFitPreferences.desiredSalaryEur.max', 'jobFitPreferences.workAuthorization.holds',
]

export const GUARDED_FIELDS = { profile: PROFILE_FIELDS, intelligence: INTELLIGENCE_FIELDS }

export class SaveRefused extends Error {
  constructor(kind, fields) {
    const shown = fields.slice(0, 6).join(', ') + (fields.length > 6 ? `, and ${fields.length - 6} more` : '')
    super(`Save refused: it would empty or cut ${fields.length} ${kind} settings that are filled in on the server (${shown}). Nothing was changed. `
      + 'This usually means the browser holds an empty or older copy: do not save from it. Earlier versions are in data/backups/auto.')
    this.name = 'SaveRefused'
    this.code = 'would_lose_data'
    this.status = 409
    this.fields = fields
  }
}

const read = (doc, dotted) => dotted.split('.').reduce((v, key) => (v && typeof v === 'object' ? v[key] : undefined), doc)

function isFilled(value) {
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'string') return value.trim() !== ''
  if (typeof value === 'number') return Number.isFinite(value)
  return false
}

/** The guarded fields of `kind` that are filled in `existing` and would be emptied, or cut by more than half, by `incoming`. */
export function findLosses(kind, existing, incoming) {
  const fields = GUARDED_FIELDS[kind]
  if (!fields) throw new Error(`Unknown save kind: ${kind}`)
  if (!existing || typeof existing !== 'object') return []
  return fields.filter((field) => {
    const before = read(existing, field)
    const after = read(incoming, field)
    if (!isFilled(before)) return false
    if (!isFilled(after)) return true
    return Array.isArray(before) && before.length >= 3 && after.length * 2 < before.length
  })
}

/** Throws SaveRefused when the save would lose GUARD_LOSS_LIMIT or more filled-in fields; logs the field names. */
export function assertSafeToReplace(kind, existing, incoming) {
  const lost = findLosses(kind, existing, incoming)
  if (lost.length < GUARD_LOSS_LIMIT) return
  console.error(`[save-guard] refused the ${kind} save: it would empty or cut ${lost.length} filled-in fields: ${lost.join(', ')}`)
  throw new SaveRefused(kind, lost)
}

/** The parsed JSON of `file`, or null when it is missing or unreadable (then there is nothing to guard). */
export function readExistingJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}
