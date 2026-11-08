// What the Jobs screen does with the two lists of `allAds.js` (slice S5e3c): the class and 14-day filters of All, the row's badges and
// what may be done with a row, and the notices. Pure, and nothing here writes anywhere. The controls behind it live in React state
// only: they are not in `state.filters`, so changing one saves nothing.
import { classLabel, seenRecently } from './allAds.js'
import { historyBadges } from './jobHistory.js'
import { filterJobs } from './jobFilters.js'

/** The nine classes of the route, and one label for display only: a stored row the route does not hold has no class. */
export const SAVED_IN_BROWSER = 'saved_in_browser'
export const CLASS_FILTERS = ['found', 'held', 'absent', 'closed', 'older_key', 'stale', 'filtered', 'filtered_incomplete', 'unclassified', SAVED_IN_BROWSER]
export const SERVER_ONLY_NOTE = 'Press Keep this ad first'
export const KEEP_FIRST_NOTE = 'This ad is not saved in this browser. AI tools, outreach, tailoring and status changes need it saved: press Keep this ad first. Mark Applied works without it.'
export const ALL_SEARCH_NOTE = 'In All, search does not match the ad text of rows not saved in this browser, only their title, company and source.'
export const INCOMPLETE_FILTERED = 'This list is incomplete: filtered ads could not be read'
export const INCOMPLETE_ROUTE = 'This list is incomplete: the full list could not be loaded, so only rows saved in this browser are shown'
export const OFF_LIST_NOTE = 'Active and All already include these rows'
export const EXPORT_NOTE = 'Export covers rows saved in this browser only, not the rows only the server holds'

const displayClass = (row) => row.class ?? SAVED_IN_BROWSER
const FILTER_LABELS = { found: 'Found', [SAVED_IN_BROWSER]: 'Saved in this browser' }

export function classFilterLabel(key) {
  return FILTER_LABELS[key] ?? classLabel({ class: key })
}

/** Each class filter with how many rows of `rows` it holds. All ten are always offered, so a class with none says so. */
export function classOptions(rows) {
  const counts = new Map()
  for (const row of rows) counts.set(displayClass(row), (counts.get(displayClass(row)) ?? 0) + 1)
  return CLASS_FILTERS.map((value) => ({ value, label: classFilterLabel(value), count: counts.get(value) ?? 0 }))
}

/** All's own filters. `classes` empty means every class. `recent` keeps rows seen in the 14 days before `reference`; hand-entered rows have no sighting. */
export function applyAllControls(rows, { classes = new Set(), recent = false, reference }) {
  return rows.filter((row) => (!classes.size || classes.has(displayClass(row))) && (!recent || seenRecently(row.lastSeen, reference)))
}

/**
 * The existing filters over a composed list. Show off-list has no job here, since the two lists already decide that. Hide no longer
 * listed reads the route's class when a row has one: the stored `isClosed` may be older.
 */
export function filterComposed(rows, filters, options) {
  const open = filters?.hideNoLongerListed ? rows.filter((row) => (row.class ? row.class !== 'closed' : row.isClosed !== true)) : rows
  return filterJobs(open, { ...filters, showOffList: true, hideNoLongerListed: false }, options)
}

/** What may be done with a row: `stored` as ever, `server` only looked at for now, `filtered` a link and Add job. */
export function rowKind(row) {
  if (!row?.serverOnly) return 'stored'
  return row.from === 'filtered' ? 'filtered' : 'server'
}

/** The rows bulk actions can reach: only stored ones. */
export const selectableIds = (rows) => rows.filter((row) => rowKind(row) === 'stored').map((row) => row.jobId)

/**
 * The badges of a row in a composed list. The class says where it stands; `isClosed` and `isAbsent` on a stored row may be older and
 * are not read. "Just found" stays, on a row the latest run has seen.
 */
export function classBadges(row) {
  const label = classLabel(row)
  const badges = label ? [{ label, variant: 'low', reason: row.reason ?? '' }] : []
  if (row.appliedOtherCopy) badges.push({ label: 'Applied to another copy', variant: 'medium', reason: 'You have an application on another listing of this ad.' })
  const seenNow = row.class === 'found' || row.class === 'held' || !row.class
  return seenNow ? [...badges, ...historyBadges({ isNew: row.isNew, firstSeen: row.firstSeen })] : badges
}

/** The notices above the list, each `{ kind, text, retry? }`. A list that is not whole never goes without saying so. */
export function listNotices({ mode, status, error, meta, rows, copies, hasServerOnly }) {
  const notices = []
  if (status === 'error') {
    const shown = rows ? 'Showing the last list loaded and what is saved in this browser' : 'Showing what is saved in this browser'
    notices.push({ kind: 'error', text: `The full list could not be loaded: ${error}. ${shown}; nothing was changed.`, retry: true })
  }
  if (mode === 'all') {
    if (!rows && status === 'error') notices.push({ kind: 'error', text: INCOMPLETE_ROUTE })
    else if (!rows) notices.push({ kind: 'info', text: `Loading the full list. ${INCOMPLETE_ROUTE.split(':')[0]} until it arrives.` })
    else if (meta?.filteredFile !== 'ok') notices.push({ kind: 'error', text: INCOMPLETE_FILTERED })
  }
  if (rows && copies?.state === 'waiting') notices.push({ kind: 'info', text: 'Copies of the same ad are shown separately until your applications have loaded.' })
  if (rows && copies?.state === 'failed') notices.push({ kind: 'error', text: 'Your applications could not be loaded: copies of the same ad are shown separately, and a row with an application may be missing from Active.' })
  if (hasServerOnly) notices.push({ kind: 'info', text: `Rows not saved in this browser are read-only until you press Keep this ad on them. Selecting and bulk actions cover saved rows only.` })
  return notices
}
