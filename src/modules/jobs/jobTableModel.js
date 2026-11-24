// Paging and selection of the Jobs table (slice S5e3b). Pure, in memory: nothing here is ever saved.
//
// Each state remembers the key it was made under, and a state from another key reads as the starting one, so a reset needs no effect
// and no list change can reset by accident. A row's status changing rebuilds the list but keeps the key.

import { isClosedAd } from './jobHistory.js'
import { isNotRead } from './matchScore.js'
import { tierIndexOf } from './fitTier.js'
import { isRemoteFeasible } from './workAuthorization.js'
import { getJobProvider } from './jobFilters.js'
import { deadlineSortValue } from './jobDeadline.js'
import { sortRows } from '../tableSort.js'

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
const descTime = (x, y) => (x === y ? 0 : x === null ? 1 : y === null ? -1 : y - x)
export const neutralCompare = (a, b) => Number(isRemoteFeasible(b)) - Number(isRemoteFeasible(a)) || descTime(postedTimeOf(a), postedTimeOf(b)) || byId(a, b)

/** Rows in the neutral order alone, for sorts whose ties would otherwise follow the arrival order. */
export const neutralOrder = (rows) => rows
  .map((row) => ({ row, feasible: Number(isRemoteFeasible(row)), posted: postedTimeOf(row) })) // once per row, as `orderDefault` does
  .sort((a, b) => b.feasible - a.feasible || descTime(a.posted, b.posted) || byId(a.row, b.row))
  .map((entry) => entry.row)

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

/**
 * The default order as ONE sort key (owner decision 2026-11-21 plus the three group rules of the table): not-read ads first, then open before closed,
 * then unblocked before blocked, then the tier (a row in no tier last), then the neutral order (remote-feasible first, newest first, jobId). It is
 * exactly `notReadFirst(closedLast(blockedLast(defaultOrder(rows))))` as one comparison, so a server can sort and page by it. The key, in order:
 * `[notRead, closed, blocked, tierIndex, notRemoteFeasible, postedTime, jobId]`, each 0/1 flag with 0 first, `tierIndex` null last (3), and
 * `postedTime` null last. Pure; the Jobs screen and the server both use it.
 */
export function defaultSortKey(row) {
  const tier = tierIndexOf(row)
  return [
    isNotRead(row) ? 0 : 1,
    isClosedAd(row) ? 1 : 0,
    (row?.blockedBy || []).length > 0 ? 1 : 0,
    tier === null ? 3 : tier,
    isRemoteFeasible(row) ? 0 : 1,
    postedTimeOf(row),
    row?.jobId,
  ]
}

/** The order of two rows under `defaultSortKey`. Zero only for the same jobId. */
export const compareDefault = (a, b) => compareDefaultKeys(defaultSortKey(a), defaultSortKey(b))

/** The order of two keys made by `defaultSortKey`. */
function compareDefaultKeys(ka, kb) {
  for (let i = 0; i < 4; i += 1) if (ka[i] !== kb[i]) return ka[i] - kb[i]
  if (ka[4] !== kb[4]) return ka[4] - kb[4]
  if (ka[5] !== kb[5]) return ka[5] === null ? 1 : kb[5] === null ? -1 : kb[5] - ka[5] // newest first, no date after dated ones
  return ka[6] === kb[6] ? 0 : String(ka[6]) < String(kb[6]) ? -1 : 1
}

/**
 * Rows in the default order. A key takes the tier, the eligibility and the dates of a row (tens of microseconds), and a sort compares each row many times, so the key is
 * made ONCE per row and the rows are sorted by their keys: the same order, and on a list of thousands of ads (a server list with the absent search-source ads scored) 4 s
 * became a few tens of milliseconds.
 */
export const orderDefault = (rows) => rows.map((row) => ({ row, key: defaultSortKey(row) })).sort((a, b) => compareDefaultKeys(a.key, b.key)).map((entry) => entry.row)

/** The columns a picked sort can use (the table's headers). `deadline` needs the day: see `orderRows`. */
export const SORT_COLUMNS = {
  // Strong fit 3, Possible 2, Weak 1 (descending = best first); a row in no tier (blocked, no score) sorts last either way. Ties keep the neutral order.
  tier: { type: 'number', value: (j) => { const i = tierIndexOf(j); return i === null ? null : 3 - i } },
  title: { type: 'text', value: (j) => j.title },
  company: { type: 'text', value: (j) => j.company },
  location: { type: 'text', value: (j) => j.location },
  salary: { type: 'number', value: (j) => j.salaryMonthlyEur?.max },
  deadline: { type: 'number', firstDir: 'asc', value: () => null }, // needs the date: filled in by `orderRows`
  provider: { type: 'text', value: (j) => getJobProvider(j) },
  status: { type: 'text', value: (j) => j.status || 'new' },
}

/** The sort the table starts in. The table tells it by identity (any click replaces it, even back to the same column). */
export const DEFAULT_SORT = { key: 'tier', dir: 'desc' }

/**
 * `rows` in the order a table sort gives: `sort` null or `DEFAULT_SORT` is the default order; a picked column sorts the rows in the neutral order,
 * so rows with an equal value always come in the same order (owner-visible change 2026-11-24: before, ties followed the arrival order of the list,
 * which differs between a browser and a server). `today` is the day string the deadline column reads.
 */
export function orderRows(rows, sort, today) {
  if (!sort || sort === DEFAULT_SORT) return orderDefault(rows)
  const columns = { ...SORT_COLUMNS, deadline: { ...SORT_COLUMNS.deadline, value: (j) => deadlineSortValue(j, today) } }
  return sortRows(neutralOrder(rows), sort, columns)
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
