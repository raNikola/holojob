// The Jobs list as one pure query: what the Jobs screen works out from its inputs, in the order it works it out, as a function of those inputs
// alone (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P1). The server route (P2) imports this file, and the screen will (P3): one source of the rules.
//
// Pure and plain data in, plain data out: no storage, no clock, no fetch, nothing is written. Every input must survive a JSON round trip, so a
// server can hold it. `reference` (a time) is a parameter, as in `composeJobList`.
//
// The pipeline is the screen's, step for step (JobDiscoveryScreen.jsx, "composedRows" to "filteredJobs", and JobTable's sort and paging):
//   1. `composeJobList` makes Active and All from the stored rows and the route's rows;
//   2. the server's statuses and Keep flags, then the application store's tracking, are laid over the rows (`withServerState`, `overlayTracking`);
//   3. All's own controls (class, "seen recently") apply;
//   4. the filters apply (`filterComposed`; All shows ads the board no longer lists, Active leaves them out unless asked);
//   5. the rows are put in order (`orderRows`: the default order or a picked column, ties in the neutral order);
//   6. the page is `offset` and `limit` of that order.
// The counts come from the same rows, so they cannot disagree with the page.
import { composeJobList, validWindowDays } from './allAds.js'
import { applyAllControls, classOptions, filterComposed, rowKind, selectableIds } from './jobListView.js'
import { jobMatchKey } from './jobStorage.js'
import { countByValue, getCompanyOptions, getUniqueProviders, getUniqueSites, hiddenAsNotOnBoard } from './jobFilters.js'
import { computeJobStats } from './jobStats.js'
import { tierCounts } from './fitTier.js'
import { orderRows } from './jobTableModel.js'
import { withServerState } from './jobStateClient.js'
import { JOB_STATUSES } from './jobStorage.js'
import { PRIORITIES, hasMatchScores } from './matchScore.js'
import { dayOf } from './jobDeadline.js'
import { overlayTracking, trackerStats } from '../applications/trackingView.js'
import { appliedJobIds, statusFilterOptions } from '../applications/appliedFilter.js'

export const LIST_MODES = ['active', 'all']
const SHOWN_PRIORITIES = PRIORITIES.filter((p) => p !== 'Reject')

/** A row the way the table shows it: the application store's work on it counts, also on a row with no stored copy. */
function shownRow(row) {
  return row.serverOnly && row.applicationTracking ? { ...row, status: 'applied_manually' } : row
}

/** The match key of each row a bulk action can reach (`{ jobId: key }`): select-all names ads of pages the browser has not loaded, and a status write needs the key. */
function selectableKeys(rows) {
  const keys = {}
  for (const row of rows) keys[row.jobId] = jobMatchKey(row)
  return keys
}

/**
 * @param {object} input
 * @param {object[]} input.stored          the stored rows (the scored list as `importJobsFromFile` makes it, and the owner's worked rows)
 * @param {object[]|null} input.server     the rows of GET /api/jobs/all, or null
 * @param {{status: string, store: object|null, settings?: object}} input.applications  as `useApplications` gives it
 * @param {object|null} input.jobStateDoc  job-state.json (statuses and Keep), or null
 * @param {number|string|Date} input.reference  the time the list is worked out at
 * @param {'active'|'all'} input.mode
 * @param {object} input.filters           the EFFECTIVE filters (the profile's salary defaults already applied by the caller)
 * @param {Iterable<string>} [input.classes]  All's class filter; empty is every class
 * @param {boolean} [input.recent]         All's "seen recently"
 * @param {object|null} [input.sort]       `{ key, dir }` of a picked column, or null for the default order
 * @param {number} input.offset            rows to skip (a whole number, 0 or more)
 * @param {number} input.limit             rows to take (a whole number, 1 or more): from Settings, never a default here
 * @param {number} [input.today]           the day the deadline column and sort read (`dayOf`, the local midnight). The caller passes the CLIENT's day: a server
 *                                         in another time zone would otherwise sort the deadline column differently near midnight. Default: `dayOf(reference)`.
 * @param {number} input.activeWindowDays the Settings period: how many days an ad the latest search did not return stays in Active after it was last seen (whole days, 1 to 365).
 *                                         Never a default here: the caller reads it from Settings, and without a valid one there is no list.
 * @param {boolean} [input.withCounts] default true. False leaves `counts` null and works none out: a "Show more" page needs the rows only, the first page's counts stand
 * @param {boolean} [input.withIds]        also return `ids` (every matching ad, in order) and `selectableIds` (those a bulk action can reach), for select-all across pages
 * @returns {{ rows: object[], total: number, offset: number, limit: number, counts: object, ids?: string[], selectableIds?: string[] }}
 */
export function queryJobList({
  stored = [], server = null, applications = null, jobStateDoc = null, reference, mode, filters = {}, classes = [], recent = false, sort = null, offset, limit, today, withIds = false, withCounts = true, activeWindowDays,
}) {
  if (!LIST_MODES.includes(mode)) throw new TypeError(`queryJobList: mode must be one of ${LIST_MODES.join(', ')}`)
  if (!Number.isInteger(offset) || offset < 0) throw new TypeError('queryJobList: offset must be a whole number, 0 or more')
  if (validWindowDays(activeWindowDays) === null) throw new TypeError('queryJobList: activeWindowDays must be a whole number of days, 1 to 365 (the Settings field)')
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError('queryJobList: limit must be a whole number, 1 or more (the page size is a Settings field)')

  const store = applications?.status === 'ready' ? applications.store : null
  const settings = applications?.settings

  const composed = composeJobList({ stored, server, applications, reference, activeWindowDays, jobStateDoc })
  const base = overlayTracking(withServerState(mode === 'all' ? composed.all : composed.active, jobStateDoc), store, settings).map(shownRow)
  const shown = mode === 'all' ? applyAllControls(base, { classes: new Set(classes), recent, reference, windowDays: activeWindowDays }) : base
  const effective = mode === 'all' ? { ...filters, showNotOnBoard: true } : filters
  const filtered = filterComposed(shown, effective, { appliedJobIds: appliedJobIds(store) })
  const ordered = orderRows(filtered, sort, today ?? dayOf(new Date(reference).getTime()))

  return {
    rows: ordered.slice(offset, offset + limit),
    total: ordered.length,
    offset,
    limit,
    activeWindowDays,
    ...(withIds ? { ids: ordered.map((row) => row.jobId), selectableIds: selectableIds(ordered, true), keys: selectableKeys(ordered.filter((row) => rowKind(row) !== 'filtered')) } : {}),
    counts: !withCounts ? null : {
      baseTotal: base.length, // the rows of this list before the controls and filters: the "of" in "N of M jobs shown"
      stats: { ...computeJobStats(overlayTracking(withServerState(stored, jobStateDoc), store, settings)), ...trackerStats(store, settings) },
      tiers: tierCounts(filtered),
      classOptions: mode === 'all' ? classOptions(base) : [],
      notOnBoardHidden: mode === 'active' ? shown.filter((job) => hiddenAsNotOnBoard(job, effective)).length : 0,
      copies: composed.copies,
      hasServerOnly: base.some((row) => row.serverOnly),
      facets: {
        hasScores: hasMatchScores(base),
        sites: getUniqueSites(base),
        providers: getUniqueProviders(base),
        companyOptions: getCompanyOptions(base),
        priorityCounts: countByValue(base, 'priority', SHOWN_PRIORITIES),
        statusOptions: statusFilterOptions(JOB_STATUSES, base, store),
      },
    },
  }
}
