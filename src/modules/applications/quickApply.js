/**
 * The quick "Applied" form behind the Jobs table button (Wave 6 j). Pure helpers: the dialog owns no state worth testing.
 * The application is written only by `submitQuickApply`, which resolves after the server's answer. Until then, and after a
 * failure or a cancel, nothing is written and no row shows Applied: the status is derived from the store (`overlayTracking`).
 */

import { markApplied, newApplicationDefaults } from './trackerController.js'

/** The form a job starts with: the same defaults as the full form and the drawer's "Mark Applied". */
export const quickApplyForm = (job, profile) => newApplicationDefaults(job, profile)

/**
 * Save the application. Resolves with the server's result only once the store has written it, rejects otherwise (a 409 for a
 * duplicate included: `error.extra.conflictingId` names the clash). `onSaved` runs after success only.
 */
export async function submitQuickApply(job, cache, form, { onSaved } = {}) {
  const result = await markApplied(job, cache, form)
  onSaved?.(result)
  return result
}
