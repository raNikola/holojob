// When to re-read the application store and the job list without being asked (another tab may have written).
// There is no server version or etag, so the check is the plain GET the cache already uses.

export const POLL_MS = 60_000
export const FOCUS_MIN_GAP_MS = 2_000

/** A draft whose form would be replaced if the application appeared elsewhere. */
const BLOCKING_DRAFTS = ['new application']

/**
 * `'refresh'` or `'skip'`.
 * @param {{ trigger: 'focus' | 'visible' | 'poll', visible: boolean, status: string, dirtyLabels: string[], sinceLastMs: number }} input
 */
export function refreshDecision({ trigger, visible, status, dirtyLabels, sinceLastMs }) {
  if (!visible || status !== 'ready') return 'skip'
  if (dirtyLabels.some((label) => BLOCKING_DRAFTS.includes(label))) return 'skip'
  const gap = trigger === 'poll' ? POLL_MS - 1_000 : FOCUS_MIN_GAP_MS
  return sinceLastMs >= gap ? 'refresh' : 'skip'
}
