/**
 * Edit Profile saves every keystroke into the profile as it is typed, so there is
 * no "unsaved" state to drop. Cancel instead puts back a copy taken when the
 * edit began.
 */

/** A deep copy that later edits cannot reach. */
export function takeProfileSnapshot(profile) {
  return JSON.parse(JSON.stringify(profile))
}

// Bookkeeping that changes whenever the profile is saved or a step is visited,
// without the candidate having changed anything.
function content(profile) {
  const { meta = {}, ...rest } = profile || {}
  const { updatedAt, lastStep, ...stableMeta } = meta // eslint-disable-line no-unused-vars
  return JSON.stringify({ ...rest, meta: stableMeta })
}

/** True when the profile now differs from the snapshot in anything the candidate entered. */
export function profileChangedSince(snapshot, profile) {
  return content(snapshot) !== content(profile)
}
