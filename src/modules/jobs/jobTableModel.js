// Paging and selection of the Jobs table (slice S5e3b). Pure, in memory: nothing here is ever saved.
//
// Each state remembers the key it was made under, and a state from another key reads as the starting one, so a reset needs no effect
// and no list change can reset by accident. A row's status changing rebuilds the list but keeps the key.

import { isClosedAd } from './jobHistory.js'
import { fitScoreOf, preCapScoreOf } from './matchScore.js'

export const JOB_PAGE_SIZE = 100
const NOTHING = new Set()

const byId = (a, b) => (a.jobId === b.jobId ? 0 : String(a.jobId) < String(b.jobId) ? -1 : 1)

/**
 * The default order: Fit Score descending, rows with no score last; equal scores by the score before caps (descending), then by jobId.
 * Rows without scoreBeforeCaps use their Fit Score. Only the default sort uses this: a sort the owner picked is left as it is.
 */
export function defaultOrder(rows) {
  const desc = (x, y) => (x === y ? 0 : x === null ? 1 : y === null ? -1 : y - x)
  return [...rows].sort((a, b) => desc(fitScoreOf(a), fitScoreOf(b)) || desc(preCapScoreOf(a), preCapScoreOf(b)) || byId(a, b))
}

/** Open ads before closed ones, each group in the order given. Only for the default sort: a sort the owner picked is left as it is. */
export function closedLast(rows) {
  return [...rows.filter((row) => !isClosedAd(row)), ...rows.filter(isClosedAd)]
}

/** How many rows are shown under `key`: paging is `{ key, limit }`, and the key holds the filters and the sort. */
export function pageLimit(paging, key) {
  return paging?.key === key ? paging.limit : JOB_PAGE_SIZE
}

/** The paging after "Show more". */
export function showMore(paging, key) {
  return { key, limit: pageLimit(paging, key) + JOB_PAGE_SIZE }
}

/** The ids selected under `key`, the filters: selection is `{ key, ids }`. Sorting and Show more do not change the key. */
export function selectionFor(selection, key) {
  return selection?.key === key ? selection.ids : NOTHING
}

export function toggleSelected(selection, key, jobId) {
  const ids = new Set(selectionFor(selection, key))
  if (!ids.delete(jobId)) ids.add(jobId)
  return { key, ids }
}

/** True when every filtered row is selected. */
export function everySelected(selected, jobIds) {
  return jobIds.length > 0 && jobIds.every((jobId) => selected.has(jobId))
}

/** Select all means every filtered row, shown or not; with all of them selected already, it clears. */
export function toggleAllSelected(selection, key, jobIds) {
  return { key, ids: everySelected(selectionFor(selection, key), jobIds) ? new Set() : new Set(jobIds) }
}

/** How many selected rows are in `allJobs` but not among the rows on screen. */
export function selectedNotShown(selected, allJobs, shownCount) {
  let count = 0
  for (let i = shownCount; i < allJobs.length; i += 1) if (selected.has(allJobs[i].jobId)) count += 1
  return count
}
