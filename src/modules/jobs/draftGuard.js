// Unsaved input in Job Details. A form registers itself while it holds something typed; leaving the drawer for
// the full page asks first (`leaveDecision`). Only forms that call `useDraftDirty` are covered.

const dirty = new Map()

export function setDraftDirty(key, label, isDirty) {
  if (isDirty) dirty.set(key, label)
  else dirty.delete(key)
}

export function dirtyDraftLabels() {
  return [...new Set(dirty.values())]
}

/** True when any field of `draft` differs from `base` (both flat objects with the same keys). */
export function draftIsDirty(base, draft) {
  return Object.keys(base).some((key) => (draft[key] ?? '') !== (base[key] ?? ''))
}

/** null: leave without asking. Otherwise the question to confirm. */
export function leaveDecision(labels) {
  if (!labels.length) return null
  return `You have unsaved input (${labels.join(', ')}). Open the full page and discard it?`
}
