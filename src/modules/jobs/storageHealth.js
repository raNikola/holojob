// How well the browser holds the job list (S8a), as one small shared state the notice reads. In memory only: nothing here is stored.
//
//   ok       the whole list is stored
//   near     the whole list is stored, and the browser is close to its limit
//   lean     stored without the ad text of rows the server has (kept, no-longer-listed and hand-entered rows keep theirs)
//   minimal  stored without any ad text but the hand-entered jobs'
//   error    NOT stored: the last saved copy is still in the browser, and what was changed since is not in it

export const STORAGE_QUOTA_CHARS = 5 * 1024 * 1024
export const NEAR_RATIO = 0.85

const START = { level: 'ok', rows: 0, chars: 0, percent: 0, droppedText: 0, textsMissing: 0 }
let state = START
const listeners = new Set()

export const getStorageHealth = () => state

export function setStorageHealth(patch) {
  const next = { ...state, ...patch }
  if (Object.keys(next).every((key) => next[key] === state[key])) return
  state = next
  listeners.forEach((listener) => listener())
}

export function subscribeStorageHealth(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** For tests. */
export function resetStorageHealth() {
  state = START
  listeners.clear()
}
