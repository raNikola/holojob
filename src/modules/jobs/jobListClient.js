// The Jobs list's side of the server list (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b). The screen calls these in P3; until then they are tested on their own.
//
// Nothing here writes: no `saveJobs`, no browser storage, no job store. A page of the server's list is held in memory by the caller, and an ad that is only a
// server row is never put into the browser's list (a stored row would count as an active job in stats, exports and AI contexts: see `jobResolve.js`).
//
// Opening an ad (the rule, owner decision 2026-11-24): the browser's own row comes first, as `resolveJob` has always done. A browser-only ad (an `offList` row, a
// hand-entered job the server was never given) is not stored on the server (the request only names it, for one request), so `/api/jobs/list/ad` cannot return
// it: it opens from the browser's local data, and its actions (status, notes, outreach, Mark Applied, tailoring) are the same code on the same stored row as before.
// An ad with no stored row opens from the server, read-only, until the owner presses Keep.
import { mergeRow } from './allAds.js'
import { isBrowserOnly, selectExtraRows } from './extraRows.js'
import { pickFilters } from './listFilters.js'
import { DEFAULT_SORT } from './jobTableModel.js'

export const LIST_URL = '/api/jobs/list'
export const AD_URL = '/api/jobs/list/ad'
export const CONTEXT_URL = '/api/jobs/list/context'

/**
 * The body of a list request. `extraRows` is the browser's own rows, as the allowlist lets them out (`selectExtraRows`). `sort` is the table's sort state:
 * the default sort (told by identity, as the table does) is sent as no sort. `today` is the browser's day for the deadline column. The page size is not a
 * parameter: it is the Settings field `jobsPageSize`, and the server answers with the one it used.
 */
export function buildListBody({ stored, mode, offset = 0, filters = {}, classes = [], recent = false, sort = null, today = null, revision = null, ids = false, countsOnly = false }) {
  return {
    mode,
    offset,
    filters: pickFilters(filters),
    classes: [...classes],
    recent,
    sort: sort && sort !== DEFAULT_SORT ? { key: sort.key, dir: sort.dir } : null,
    ...(today === null ? {} : { today }),
    ...(revision ? { revision } : {}),
    ...(ids ? { ids: true } : {}),
    ...(countsOnly ? { countsOnly: true } : {}),
    // The ad's text is most of a row's bytes and only a text search reads it: it goes only while a search is on.
    extraRows: selectExtraRows(stored, { withText: Boolean(String(filters?.searchText ?? '').trim()) }),
  }
}

/**
 * The words for a list request the server refused as too large (a 413): how many rows of what kind, the cap the server named, what is not done, what to do.
 * Never an empty or shorter list: the screen shows this instead.
 */
export function tooLargeMessage(extraRows, limitBytes) {
  const rows = extraRows ?? []
  const manual = rows.filter((row) => row.manualEntry === true).length
  const offList = rows.filter((row) => row.offList === true).length
  const flags = rows.length - manual - offList
  const cap = Number.isFinite(limitBytes) ? ` of ${Math.round(limitBytes / 1024)} KB` : ''
  return `The list could not be loaded: this browser holds ${rows.length} ads the server's list does not (${manual} hand-entered, ${offList} that left the list, ${flags} with your work on a server ad), and sending them with the list request is over its size limit${cap}. `
    + 'Nothing was cut and no list was made. To fix it, delete hand-entered jobs you no longer need (Job Details, Delete): that is the only removal there is today.'
}

/**
 * One page, or why there is none. Never throws, and a refusal is never an empty list: `{ ok: false, message }` is shown to the owner as it is.
 * `{ ok: true, changed: true, revision }` says the list moved since the revision sent: the caller starts again from the first page.
 */
export async function fetchListPage(body, fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn(LIST_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const json = await res.json().catch(() => null)
    if (res.ok && json?.ok === true) return json.changed ? { ok: true, changed: true, revision: json.revision } : { ok: true, page: json }
    if (res.status === 413) return { ok: false, status: 413, tooLarge: true, rowCount: (body.extraRows ?? []).length, message: tooLargeMessage(body.extraRows, json?.limitBytes) }
    return { ok: false, status: res.status, message: json?.message || json?.error || `The list could not be loaded (${res.status}).` }
  } catch (error) {
    return { ok: false, status: 0, message: `The list could not be loaded: ${error.message}` }
  }
}

/** What only the owner's own copy of a row holds (the server's list has none of it): laid over the server's row when the browser has the ad. */
const OWNER_ROW_FIELDS = ['tailoredAssets', 'aiInsights', 'outreach', 'notes', 'extraLinks', 'sourceUrl', 'sourceChoice', 'keptRescoredAt']

/**
 * The rows of a page as the list shows them.
 *  - A browser-only row (`offList`, hand-entered) is the browser's own copy with the server's class and reason laid over it.
 *  - A row the browser also holds is the server's row (its ad fields, score and tier are the server's, so a stale browser copy cannot show an old score) with the
 *    owner's own fields from the browser's copy laid over it (assets, insights, outreach, notes).
 *  - A row only the server holds is the server's row, marked `serverOnly`: read-only until the owner presses Keep (status and Mark Applied work on it).
 * Nothing here is written anywhere.
 */
export function listRows(rows, stored) {
  const local = new Map((stored ?? []).map((job) => [job.jobId, job]))
  return rows.map((row) => {
    const mine = local.get(row.jobId)
    if (!mine) return row.serverOnly ? row : { ...row, serverOnly: true }
    // mergeRow takes the route's fields only: the History reason the server worked out for this row comes along as well.
    if (isBrowserOnly(mine)) return { ...mergeRow(mine, row), ...(row.historyState ? { historyState: row.historyState, historyReason: row.historyReason } : {}) }
    const { serverOnly: _serverOnly, ...held } = row
    return { ...held, ...Object.fromEntries(OWNER_ROW_FIELDS.filter((field) => mine[field] !== undefined).map((field) => [field, mine[field]])) }
  })
}

export const shownRows = (page, stored) => listRows(page.rows, stored)

/**
 * Where an ad opens from. The stored row first, whatever it is (a browser-only ad, or one the owner has worked on): `source: 'local'`, nothing fetched, and
 * the caller writes to it as it always did. With no stored row the server's full row, `source: 'server'`, `readOnly: true`. `source: 'none'` (the server has
 * no scored row either) leaves the caller to the ledger fallback of `resolveJob`. Reads only.
 */
export async function openAd({ jobId, stored, fetchFn = globalThis.fetch }) {
  const local = (stored ?? []).find((job) => job.jobId === jobId)
  if (local) return { source: 'local', row: local, readOnly: false }
  const ad = await fetchServerAd(jobId, fetchFn)
  return ad.ok ? { source: 'server', row: ad.row, readOnly: true, revision: ad.revision } : { source: 'none', status: ad.status, message: ad.message }
}

/** The server's full row of one scored ad (`GET /api/jobs/list/ad`), whether or not the browser holds it. Reads only. */
export async function fetchServerAd(jobId, fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn(`${AD_URL}?jobId=${encodeURIComponent(jobId)}`)
    const json = await res.json().catch(() => null)
    if (res.ok && json?.ok === true) return { ok: true, row: json.row, revision: json.revision }
    return { ok: false, status: res.status, message: json?.error ?? null }
  } catch (error) {
    return { ok: false, status: 0, message: error.message }
  }
}

/** The numbers of the whole list with no rows (the Dashboard's cards, the AI context's totals): `{ ok: true, counts, total }` or `{ ok: false, message }`. */
export async function fetchListCounts({ stored, mode = 'active', fetchFn = globalThis.fetch }) {
  const answer = await fetchListPage(buildListBody({ stored, mode, countsOnly: true }), fetchFn)
  if (!answer.ok) return answer
  return answer.changed ? { ok: false, message: 'The list changed while its numbers were read.' } : { ok: true, counts: answer.page.counts, total: answer.page.total }
}

/** What the AI context reads of the whole list: `{ ok: true, topJobs, skillGap }` or `{ ok: false, message }`. */
export async function fetchJobContext(fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn(CONTEXT_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    const json = await res.json().catch(() => null)
    if (res.ok && json?.ok === true) return { ok: true, topJobs: json.topJobs, skillGap: json.skillGap }
    return { ok: false, message: json?.message || json?.error || `The job context could not be loaded (${res.status}).` }
  } catch (error) {
    return { ok: false, message: error.message }
  }
}
