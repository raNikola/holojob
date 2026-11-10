// Client of the temporary must-have review (scripts/calibration-musts.js). The server holds every answer and
// returns the engine's verdict only with a saved answer; nothing here is stored in the browser.

export const MUSTS_HASH = '#/calibration/musts'

/** True for the direct route of the must-have review. It is not in any navigation. */
export const isMustsHash = (hash) => hash === MUSTS_HASH || hash === `${MUSTS_HASH}/`

export const IS_MUST_OPTIONS = [
  { value: 'yes', label: 'Yes, a real must' },
  { value: 'nice', label: 'Nice to have' },
  { value: 'no', label: 'Not a requirement' },
]
export const MEETS_OPTIONS = [
  { value: 'yes', label: 'Yes' },
  { value: 'partial', label: 'Partly' },
  { value: 'no', label: 'No' },
  { value: 'unknown', label: "Can't tell" },
]
export const VERDICT_TEXT = {
  MET: 'Met',
  PARTIAL: 'Partly met',
  MISSING: 'Not found in the CV evidence',
  UNKNOWN: 'Cannot tell from the CV evidence',
}
export const KIND_TEXT = {
  skill: 'Skill or tool', experience: 'Experience', domain: 'Domain', education: 'Education',
  certification: 'Certification', language: 'Language', other: 'Other',
}

async function readAnswer(res) {
  let data = null
  try {
    data = await res.json()
  } catch {
    // an answer that is not JSON is reported below
  }
  if (!res.ok) throw new Error(data?.error || `The server answered ${res.status}`)
  return data
}

export async function fetchMusts(fetchFn = fetch) {
  return readAnswer(await fetchFn('/api/calibration/musts'))
}

export async function saveMustAnswer(answer, fetchFn = fetch) {
  const res = await fetchFn('/api/calibration/musts/labels', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ itemId: answer.itemId, isMust: answer.isMust, meets: answer.meets }),
  })
  return readAnswer(res)
}

/** The index of the first item with no saved answer at or after `from` (wrapping), or -1 when all are answered. */
export function nextUnanswered(items, from = 0) {
  const n = items.length
  for (let step = 0; step < n; step += 1) {
    const index = (from + step) % n
    if (!items[index].label) return index
  }
  return -1
}

export const isComplete = (draft) => draft.isMust !== null && draft.meets !== null
