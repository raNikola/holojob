// Client of the temporary calibration review (scripts/calibration-review.js). The server holds every label;
// nothing here is stored in the browser.

export const CALIBRATION_HASH = '#/calibration'

/** True for the direct route of the review screen. It is not in any navigation. */
export const isCalibrationHash = (hash) => hash === CALIBRATION_HASH || hash === `${CALIBRATION_HASH}/`

export const FUNCTION_OPTIONS = [
  { value: 'yes', label: 'Yes' },
  { value: 'partial', label: 'Partly' },
  { value: 'no', label: 'No' },
]
export const REQUIREMENT_OPTIONS = [
  { value: 'yes', label: 'Yes' },
  { value: 'partial', label: 'Partly' },
  { value: 'no', label: 'No' },
  { value: 'unknown', label: "Can't tell" },
]
export const OVERALL_OPTIONS = [
  { value: 0, label: 'Not relevant' },
  { value: 1, label: 'Weak option' },
  { value: 2, label: 'Relevant' },
  { value: 3, label: 'Strong, I would apply' },
]

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

export async function fetchReview(fetchFn = fetch) {
  return readAnswer(await fetchFn('/api/calibration/review'))
}

export async function saveJudgment(judgment, fetchFn = fetch) {
  const res = await fetchFn('/api/calibration/labels', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jobId: judgment.jobId, functionFit: judgment.functionFit, hardRequirements: judgment.hardRequirements, overall: judgment.overall,
    }),
  })
  return readAnswer(res)
}

/** The index of the first ad with no saved label at or after `from` (wrapping), or -1 when all are reviewed. */
export function nextUnreviewed(items, from = 0) {
  const n = items.length
  for (let step = 0; step < n; step += 1) {
    const index = (from + step) % n
    if (!items[index].label) return index
  }
  return -1
}

/** What a card starts with: the saved label, else the AI proposal, else nothing chosen. */
export function startingJudgment(item) {
  const source = item.label ?? item.proposal
  return {
    functionFit: source?.functionFit ?? null,
    hardRequirements: source?.hardRequirements ?? null,
    overall: source?.overall ?? null,
  }
}

export const isComplete = (j) => j.functionFit !== null && j.hardRequirements !== null && j.overall !== null
