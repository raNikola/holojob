// Every ad known, as the Jobs screen will show it: the rows of GET /api/jobs/all merged over the browser's stored rows (slice S5e3a).
//
// Pure, and nothing here writes anywhere. Server-only rows stay out of `saveJobs` and `importJobsFromFile`: the merged rows are for
// display and are recomputed from the same inputs whenever one of them changes (the route answers, the application store arrives, the
// date moves). Classes are the route's (python/job_discovery/all_ads.py); this file never works one out. It only decides which rows
// a class lets into Active, because the owner's work on a row is known only here.
import { hasUserData, jobMatchKey } from './jobStorage.js'
import { identityJobUrl } from './manualJob.js'

/** How long an absent row stays in Active after it was last seen. A visibility rule, not proof the ad is still open. */
export const ACTIVE_WINDOW_MS = 14 * 24 * 60 * 60 * 1000

/** From the route whatever it says, null included. Display only: never stored on a job. */
export const ROUTE_FIELDS = ['class', 'reason', 'reasonCode', 'from', 'copyGroup', 'firstSeen', 'lastSeen', 'closedAt', 'absentSince']
/** From the route when it has a value, else the stored one. */
export const AD_FIELDS = ['title', 'company', 'location', 'jobUrl', 'provider', 'site', 'isRemote', 'datePosted']

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
const NOT_IN_ROUTE_LABEL = 'Saved in this browser'
const COPY_RANK = { found: 0, held: 1, absent: 2 }

/** The badge text of a row, or null when it needs none: a found row, a hand-entered one. */
export function classLabel(row) {
  if (row?.manualEntry) return null
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

/** Seen within the window of `now`, the end included. A row with no usable date is not: nothing says it was seen. */
export function seenRecently(lastSeen, now) {
  const seen = toTime(lastSeen)
  return seen !== null && now - seen <= ACTIVE_WINDOW_MS
}

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

function isEligible({ row, local }, now) {
  if (row.manualEntry) return true
  if (!row.class) return !local?.offList // the route says nothing about this stored row: the rule it has always had
  if (row.class === 'found' || row.class === 'held') return true
  return row.class === 'absent' && seenRecently(row.lastSeen, now)
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
 * the date moves, with no new import.
 *
 * `all` is every row. `active` is found, held, hand-entered and absent seen within the window, plus any row with the owner's work
 * on it whatever its class, with one row per ad. While the application store is loading, or if it failed, its work is not known, so
 * copies are not collapsed (`copies.state` says which). A stored row is in the result whatever the route answers.
 * @returns {{ active: object[], all: object[], copies: { state: 'collapsed'|'waiting'|'failed', hidden: number } }}
 */
export function composeJobList({ stored = [], server = null, applications = null, reference }) {
  const now = toTime(reference)
  if (now === null) throw new TypeError('composeJobList needs the current time as `reference`')
  const state = storeState(applications)
  const applied = state === 'ready' ? jobsWithApplications(applications.store) : new Set()

  const entries = pairRows(stored, server).map(({ local, route }) => {
    const entry = { local, row: mergeRow(local, route) }
    entry.worked = hasUserData(local) || applied.has(entry.row.jobId) || applied.has(route?.jobId)
    entry.eligible = isEligible(entry, now)
    return entry
  })

  const candidates = entries.filter((entry) => entry.eligible || entry.worked)
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
    active: shown.map((entry) => entry.row),
    all: entries.map((entry) => entry.row),
    copies: { state: state === 'ready' ? 'collapsed' : state === 'failed' ? 'failed' : 'waiting', hidden: candidates.length - shown.length },
  }
}
