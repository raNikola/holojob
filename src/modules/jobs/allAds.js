// Every ad known, as the Jobs screen will show it: the rows of GET /api/jobs/all merged over the browser's stored rows (slice S5e3a).
//
// Pure, and nothing here writes anywhere. Server-only rows stay out of `saveJobs` and `importJobsFromFile`: the merged rows are for
// display and are recomputed from the same inputs whenever one of them changes (the route answers, the application store arrives, the
// date moves). Classes are the route's (python/job_discovery/all_ads.py); this file never works one out. It only decides which rows
// a class lets into Active, because the owner's work on a row is known only here.
import { hasUserData, jobMatchKey } from './jobStorage.js'
import { isClosedAd } from './jobHistory.js'
import { identityJobUrl } from './manualJob.js'

const DAY_MS = 24 * 60 * 60 * 1000

/** A usable period from Settings: whole days, 1 to 365. Anything else (not loaded yet, a hand-edited file) is no period, and no number is made up. */
export function validWindowDays(value) {
  return Number.isInteger(value) && value >= 1 && value <= 365 ? value : null
}

/** From the route whatever it says, null included. Display only: never stored on a job. */
export const ROUTE_FIELDS = ['class', 'reason', 'reasonCode', 'from', 'copyGroup', 'firstSeen', 'lastSeen', 'closedAt', 'absentSince', 'repostCount']
/** From the route when it has a value, else the stored one. */
export const AD_FIELDS = ['title', 'company', 'location', 'jobUrl', 'provider', 'site', 'isRemote', 'datePosted', 'salary', 'expiresAt']

/** On a composed row for display, and never on a stored one. */
export const DISPLAY_ONLY_FIELDS = ['class', 'reason', 'reasonCode', 'from', 'copyGroup', 'serverOnly', 'appliedOtherCopy', 'historyState', 'historyReason', 'repostCount']

/** A composed row without what must not be stored or sent on. */
export function stripDisplayFields(row) {
  const copy = { ...row }
  for (const field of DISPLAY_ONLY_FIELDS) delete copy[field]
  return copy
}

const CLASS_LABELS = {
  found: null,
  held: 'Not checked this run',
  absent: 'Not in latest search',
  closed: 'Closed',
  older_key: 'Search settings changed',
  stale: 'Stale',
  filtered: 'Filtered out',
  filtered_incomplete: 'Incomplete',
  unclassified: 'Status unknown',
}
const HISTORY_LABELS = { archived: 'Archived', expired: 'Expired' }
const NOT_IN_ROUTE_LABEL = 'Saved in this browser'
const COPY_RANK = { found: 0, held: 1, absent: 2 }

/** The badge text of a row, or null when it needs none: a found row, a hand-entered one. */
export function classLabel(row) {
  if (row?.manualEntry) return null
  if (row?.historyState) return HISTORY_LABELS[row.historyState]
  if (!row?.class) return NOT_IN_ROUTE_LABEL
  return Object.hasOwn(CLASS_LABELS, row.class) ? CLASS_LABELS[row.class] : CLASS_LABELS.unclassified
}

/**
 * One row from the stored row and the route's row of an ad, field by field. User data and everything the route does not carry (the
 * description, the score, facts) stay as stored, so the route's `matchScore: null` cannot remove a score. A hand-entered job is
 * entirely the owner's. The stored row's `jobId` stays: that is what a later write goes to.
 */
export function mergeRow(stored, route) {
  if (!route) return stored ? { ...stored } : null
  if (!stored) return { ...route, status: 'new', serverOnly: true }
  if (stored.manualEntry) return { ...stored }
  const merged = { ...stored }
  for (const field of ROUTE_FIELDS) merged[field] = route[field] ?? null
  for (const field of AD_FIELDS) if (route[field] != null) merged[field] = route[field]
  return merged
}

function toTime(value) {
  const time = value instanceof Date ? value.getTime() : typeof value === 'number' ? value : Date.parse(value)
  return Number.isFinite(time) ? time : null
}

/** Seen within `windowDays` of `now` (the Settings period), the end included. A row with no usable date is not: nothing says it was seen.
 *  With no valid period nothing counts as recent: the period is Settings' to give, and code supplies none. */
export function seenRecently(lastSeen, now, windowDays) {
  const days = validWindowDays(windowDays)
  const seen = toTime(lastSeen)
  return days !== null && seen !== null && now - seen <= days * DAY_MS
}

const dayLabel = (days) => `${days} ${days === 1 ? 'day' : 'days'}`
const FILTERED_CLASSES = new Set(['filtered', 'filtered_incomplete'])

/**
 * Why a row is in History and not Active, as two separate reasons (owner decisions 2026-11-25, PACKAGES_PLAN "Closed decisions"):
 * `expired` = the deadline passed or the ad is confirmed closed (class `closed`), nothing else; `archived` = any other row not seen for the
 * Settings period (`activeWindowDays`), whatever its class (absent, older_key, stale, unclassified). Only a Saved ad, an ad with an
 * application (one in the store, or marked applied by hand) and a kept ad are never archived (owner decisions 2026-11-26); they can still be
 * expired. A Rejected ad and any other work are archived by the same N. A row seen again is `found`, so it is neither and returns to Active
 * by the same rules as any new ad (a Rejected one stays out by its status). Filtered rows keep their own class. No valid period means no
 * archiving: code supplies no number. Display only, nothing is deleted.
 * @returns {{ state: 'archived'|'expired'|null, reason: string|null }}
 */
export function historyStateOf(row, { protectedAd, now, windowDays }) {
  const none = { state: null, reason: null }
  if (row.manualEntry) return none
  if (isClosedAd(row)) return { state: 'expired', reason: 'Expired: the ad is confirmed closed' }
  const deadline = toTime(row.expiresAt)
  if (deadline !== null && deadline < now) return { state: 'expired', reason: `Expired: the deadline passed on ${new Date(deadline).toISOString().slice(0, 10)}` }
  const days = validWindowDays(windowDays)
  if (days === null || protectedAd || !row.class || row.class === 'found' || row.class === 'held' || FILTERED_CLASSES.has(row.class)) return none
  if (seenRecently(row.lastSeen, now, days)) return none
  const seen = toTime(row.lastSeen)
  const text = seen === null ? `never seen in the last ${dayLabel(days)}` : `not seen for ${dayLabel(Math.floor((now - seen) / DAY_MS))}`
  return { state: 'archived', reason: `Archived: ${text}` }
}

/** The two statuses that keep an ad out of Archived: Saved, and applied by hand (an application in the store protects on its own). */
const PROTECTED_STATUSES = new Set(['saved', 'applied_manually'])

function storeState(applications) {
  if (applications?.status === 'ready') return 'ready'
  if (applications?.status === 'error' || applications?.status === 'failed') return 'failed'
  return 'loading'
}

/** Every job with an application, voided ones too: the owner worked on it. */
function jobsWithApplications(store) {
  const ids = new Set()
  for (const app of Object.values(store?.applications ?? {})) if (app.posting?.jobId) ids.add(app.posting.jobId)
  return ids
}

/** The stored and route row of each ad. Stored rows in their own order, then server-only rows by id, so the route's order plays no part. */
function pairRows(stored, server) {
  const handEntered = new Set(stored.filter((job) => job.manualEntry).map((job) => identityJobUrl(job.jobUrl)).filter(Boolean))
  const routeRows = (Array.isArray(server) ? server : []).filter((row) => row?.jobId).sort((a, b) => (a.jobId < b.jobId ? -1 : a.jobId > b.jobId ? 1 : 0))
  const storedIds = new Set(stored.map((job) => job.jobId))
  const routeOf = new Map()
  const rest = []
  for (const row of routeRows) {
    if (storedIds.has(row.jobId)) routeOf.set(row.jobId, row)
    else rest.push(row)
  }
  // The same match the import makes: an ad stored under another id, at the same address.
  const byKey = new Map(stored.filter((job) => !routeOf.has(job.jobId)).map((job) => [jobMatchKey(job), job]))
  const serverOnly = []
  for (const row of rest) {
    const url = identityJobUrl(row.jobUrl)
    if (url && handEntered.has(url)) continue // the hand-entered job is this ad, as on import
    const match = byKey.get(jobMatchKey(row))
    if (match && !routeOf.has(match.jobId)) routeOf.set(match.jobId, row)
    else serverOnly.push(row)
  }
  return [
    ...stored.map((job) => ({ local: job, route: routeOf.get(job.jobId) ?? null })),
    ...serverOnly.map((route) => ({ local: null, route })),
  ]
}

function isEligible({ row, local }, now, windowDays) {
  if (row.manualEntry) return true
  if (!row.class) return !local?.offList && !isClosedAd(row) // the route says nothing about this stored row
  if (row.class === 'found' || row.class === 'held') return true
  return row.class === 'absent' && seenRecently(row.lastSeen, now, windowDays)
}

function betterCopy(a, b) {
  const rank = COPY_RANK[a.row.class] - COPY_RANK[b.row.class]
  if (rank) return rank < 0 ? a : b
  const seen = (toTime(b.row.lastSeen) ?? 0) - (toTime(a.row.lastSeen) ?? 0)
  if (seen) return seen < 0 ? a : b
  return a.row.jobId < b.row.jobId ? a : b
}

/** The copies of one ad that stay in Active. Every worked copy does. A worked copy in Active's own classes stands for the ad; with none,
 *  the best unworked copy does, so a copy worked on and since closed cannot hide the live one. */
function copiesToShow(copies) {
  const worked = copies.filter((copy) => copy.worked)
  if (worked.some((copy) => copy.eligible)) return worked
  const unworked = copies.filter((copy) => !copy.worked)
  return unworked.length ? [...worked, unworked.reduce(betterCopy)] : worked
}

/**
 * The two lists of the Jobs screen. `stored`: the browser's rows. `server`: the route's rows, or null with no answer. `applications`:
 * `{ status, store }`, as `useApplications` gives it. `reference`: the current time, a parameter so the list can be worked out again as
 * the date moves, with no new import. `activeWindowDays`: the Settings period an absent row stays in Active (null until Settings has answered: then no absent row is in Active).
 *
 * `all` is every row. `active` is found, held, hand-entered and absent seen within the Settings period, plus any row with the owner's work
 * on it unless the ad is closed or archived (`historyStateOf`: only Saved, applied and kept ads are never archived; an unprotected closed ad stays in History and in
 * the Application Tracker, work or no work), and no unprotected ad past its deadline, with one row per ad. A protected ad (Saved, applied, Keep) that is closed or past its deadline
 * stays in Active and carries `historyState: 'expired'` there too, so its Expired badge shows. `jobStateDoc`: the server's statuses and Keep (data/jobs/job-state.json),
 * which win over the stored row's, so a Saved ad held only there is protected too. While the application store is loading, or if it failed, its work is not known, so
 * copies are not collapsed (`copies.state` says which). A stored row is in the result whatever the route answers.
 * @returns {{ active: object[], all: object[], copies: { state: 'collapsed'|'waiting'|'failed', hidden: number } }}
 */
export function composeJobList({ stored = [], server = null, applications = null, reference, activeWindowDays = null, jobStateDoc = null }) {
  const now = toTime(reference)
  if (now === null) throw new TypeError('composeJobList needs the current time as `reference`')
  const state = storeState(applications)
  const applied = state === 'ready' ? jobsWithApplications(applications.store) : new Set()

  const entries = pairRows(stored, server).map(({ local, route }) => {
    const entry = { local, row: mergeRow(local, route) }
    const serverState = jobStateDoc?.jobs?.[jobMatchKey(entry.row)] ?? null
    const status = serverState?.status ?? local?.status ?? null
    entry.applied = applied.has(entry.row.jobId) || applied.has(route?.jobId)
    entry.worked = hasUserData(local) || entry.applied || serverState?.keep === true || (status !== null && status !== 'new')
    entry.eligible = isEligible(entry, now, activeWindowDays)
    // Saved, an application or Keep (owner decision 2026-11-26). The server stores a hand-applied ad as `new` (applied is derived), so the
    // stored row's own mark counts as well.
    entry.protectedAd = entry.applied || PROTECTED_STATUSES.has(status) || local?.status === 'applied_manually' || local?.keptByUser === true || serverState?.keep === true
    entry.history = historyStateOf(entry.row, { protectedAd: entry.protectedAd, now, windowDays: activeWindowDays })
    entry.shownRow = entry.history.state ? { ...entry.row, historyState: entry.history.state, historyReason: entry.history.reason } : entry.row
    return entry
  })

  // Out of Active: an archived row, and an expired one unless protected (a protected ad that is closed or past its deadline stays, with its Expired badge).
  // Worked-on rows are candidates unless closed; a protected closed ad is a candidate too (owner decision 2026-11-27), any other closed ad is History only.
  const leavesActive = (entry) => entry.history.state === 'archived' || (entry.history.state === 'expired' && !entry.protectedAd)
  const candidates = entries.filter((entry) => !leavesActive(entry) && (entry.eligible || (entry.worked && (entry.protectedAd || !isClosedAd(entry.row)))))
  const appliedGroups = new Set(entries.filter((entry) => entry.applied && entry.row.copyGroup).map((entry) => entry.row.copyGroup))
  const marked = (entry) => (!entry.applied && appliedGroups.has(entry.row.copyGroup) ? { ...entry.shownRow, appliedOtherCopy: true } : entry.shownRow)
  let shown = candidates
  if (state === 'ready') {
    const groups = new Map()
    for (const entry of candidates) {
      const group = entry.row.copyGroup // only ever from the route: a hand-entered row takes no route field, so it has none
      if (group) groups.set(group, [...(groups.get(group) ?? []), entry])
    }
    const hidden = new Set()
    for (const copies of groups.values()) {
      const keep = new Set(copiesToShow(copies))
      for (const copy of copies) if (!keep.has(copy)) hidden.add(copy)
    }
    shown = candidates.filter((entry) => !hidden.has(entry))
  }
  return {
    active: shown.map(marked),
    all: entries.map((entry) => entry.shownRow),
    copies: { state: state === 'ready' ? 'collapsed' : state === 'failed' ? 'failed' : 'waiting', hidden: candidates.length - shown.length },
  }
}
