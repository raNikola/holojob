// Paging and selection of the Jobs table (slice S5e3b). Pure, in memory: nothing here is ever saved.
//
// Each state remembers the key it was made under, and a state from another key reads as the starting one, so a reset needs no effect
// and no list change can reset by accident. A row's status changing rebuilds the list but keeps the key.

import { isClosedAd } from './jobHistory.js'
import { isNotRead } from './matchScore.js'
import { tierIndexOf } from './fitTier.js'
import { isRemoteFeasible } from './workAuthorization.js'

export const JOB_PAGE_SIZE = 100
const NOTHING = new Set()

const byId = (a, b) => (a.jobId === b.jobId ? 0 : String(a.jobId) < String(b.jobId) ? -1 : 1)

/** When the ad was posted (`datePosted`, else `firstSeen`) as a time, or null when neither is a readable date. */
export function postedTimeOf(row) {
  for (const value of [row?.datePosted, row?.firstSeen]) {
    const time = typeof value === 'string' && value ? Date.parse(value) : NaN
    if (Number.isFinite(time)) return time
  }
  return null
}

/**
 * The neutral order inside a group (owner decision 2026-11-21, option A): the ads that can be taken from Serbia as they stand first
 * (`isRemoteFeasible`, eligibility, owner decision 2026-11-18), then newest first (`datePosted`, else `firstSeen`; no readable date after
 * dated ones), then jobId. The Fit Score takes no part in it: no ordering inside a tier is proven (experiment B, docs/DECISIONS.md).
 */
const neutralCompare = (a, b) => {
  const desc = (x, y) => (x === y ? 0 : x === null ? 1 : y === null ? -1 : y - x)
  return Number(isRemoteFeasible(b)) - Number(isRemoteFeasible(a)) || desc(postedTimeOf(a), postedTimeOf(b)) || byId(a, b)
}

/** Rows in the neutral order alone, for sorts whose ties would otherwise follow the arrival order. */
export const neutralOrder = (rows) => [...rows].sort(neutralCompare)

/**
 * The default order (owner decision 2026-11-21, replaces 2026-11-18): by tier (`fitTier.js`: Strong, Possible, Weak fit), then the neutral
 * order. Rows in no tier (no Fit Score, blocked) go last. It only orders: no score, tier or verdict changes. Only the default sort uses
 * this: a sort the owner picked is left as it is.
 */
export function defaultOrder(rows) {
  const tier = (row) => tierIndexOf(row)
  return [...rows].sort((a, b) => {
    const ta = tier(a)
    const tb = tier(b)
    if (ta !== tb) return ta === null ? 1 : tb === null ? -1 : ta - tb
    return neutralCompare(a, b)
  })
}

/** Open ads before closed ones, each group in the order given. Only for the default sort: a sort the owner picked is left as it is. */
export function closedLast(rows) {
  return [...rows.filter((row) => !isClosedAd(row)), ...rows.filter(isClosedAd)]
}

/**
 * Not-read ads (no description, so no Fit Score) as their own group ahead of the rated ones, each group in the order given.
 * Only for the default sort. They are not sorted to the bottom as if they were the lowest score: they have none.
 */
export function notReadFirst(rows) {
  return [...rows.filter(isNotRead), ...rows.filter((row) => !isNotRead(row))]
}

/** Ads with a blocking fact (`blockedBy`, python/job_scoring/blocking.py) after the others, each group in the order given. Only for the default sort; nothing is hidden. */
export function blockedLast(rows) {
  const blocked = (row) => (row?.blockedBy || []).length > 0
  return [...rows.filter((row) => !blocked(row)), ...rows.filter(blocked)]
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
