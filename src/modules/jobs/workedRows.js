// Bringing the rows the browser HOLDS up to date with the last scoring, without loading the whole scored list
// (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P3 S6 / P4). Until now an import put every scored ad into the browser's list; with the server's list the browser holds
// only the owner's worked rows, and this is what an import does for them: the server returns the scored rows of the ads named (`POST /api/jobs/list/rows`), and each
// stored row takes the new pipeline fields (score, tier, facts of the ad) while keeping what is the owner's (status, notes, outreach, assets, insights, Keep, tracking).
// An ad the scored list no longer holds, that the owner has worked on, is marked `offList`, as an import marks it; one with no work on it just goes.
import { hasUserData, mergeStatusOnImport } from './jobStorage.js'

export const ROWS_URL = '/api/jobs/list/rows'

const blank = (text) => !String(text ?? '').trim()

/**
 * The stored `jobs` with the server's answer (`{ rows, missing }`) laid over them. Pure: nothing is written, nothing else of `jobs` changes.
 * A hand-entered job is never dropped (it may not be on the server yet); a row the server did not name is left as it is.
 */
export function applyRowsRefresh(jobs, { rows = [], missing = [] }) {
  const named = new Set([...rows.map((row) => row.jobId), ...missing])
  const heldFresh = jobs.filter((job) => rows.some((row) => row.jobId === job.jobId))
  const merged = new Map(mergeStatusOnImport(heldFresh, rows).map((row) => [row.jobId, row]))
  const gone = new Set(missing)
  const out = []
  for (const job of jobs) {
    if (merged.has(job.jobId)) {
      const row = merged.get(job.jobId)
      // the ad's own text stays when the answer brings none (a kept or off-list ad's text exists only here and in the ledger)
      out.push(blank(row.description) && !blank(job.description) ? { ...row, description: job.description } : row)
    } else if (gone.has(job.jobId)) {
      if (job.manualEntry) out.push(job)
      else if (hasUserData(job)) out.push({ ...job, offList: true })
      // an ad with no work of the owner's that the scored list no longer holds is dropped, as an import drops it
    } else {
      out.push(job)
    }
  }
  return out.filter((job) => named.has(job.jobId) || jobs.some((before) => before.jobId === job.jobId))
}

/** The server's answer for these ads: `{ ok: true, answer }` or `{ ok: false, error }`. Reads only. */
export async function fetchWorkedRows(jobIds, fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn(ROWS_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobIds }) })
    const answer = await res.json().catch(() => null)
    if (!res.ok || answer?.ok !== true) return { ok: false, error: answer?.message || answer?.error || `The scored rows could not be loaded (${res.status}).` }
    return { ok: true, answer }
  } catch (error) {
    return { ok: false, error: `The scored rows could not be loaded: ${error.message}` }
  }
}

/** The stored state with the server's answer laid over it, `importedAt` stamped so a screen reads its list again. Pure. */
export function applyWorkedRows(state, answer) {
  return { ...state, jobs: applyRowsRefresh(state.jobs, answer), meta: answer.meta ?? state.meta, importedAt: new Date().toISOString() }
}

/**
 * Asks the server for the rows of the ads in `state.jobs` and returns `{ state, changed }`, or `{ error }` (the stored list is then left exactly as it is: a failed
 * refresh changes nothing). `state.importedAt` is stamped so a screen reads its list again.
 */
export async function refreshWorkedRows(state, fetchFn = globalThis.fetch) {
  const jobIds = [...new Set((state.jobs ?? []).map((job) => job.jobId).filter(Boolean))]
  if (!jobIds.length) return { state, changed: false }
  const got = await fetchWorkedRows(jobIds, fetchFn)
  if (!got.ok) return { error: got.error }
  const next = applyWorkedRows(state, got.answer)
  return { state: next, changed: JSON.stringify(next.jobs) !== JSON.stringify(state.jobs) }
}

/**
 * Takes rows into the stored list: an ad the owner has just made theirs (tailored documents for it, a job imported by its address). A row already held is brought up
 * to date with the import's rules; a row not held is added; no other row is touched (nothing is marked off the list). Pure.
 */
export function adoptRows(jobs, rows) {
  if (!rows.length) return jobs
  const ids = new Set(rows.map((row) => row.jobId))
  const refreshed = new Map(mergeStatusOnImport(jobs.filter((job) => ids.has(job.jobId)), rows).map((row) => [row.jobId, row]))
  const held = new Set(jobs.map((job) => job.jobId))
  return [...jobs.map((job) => refreshed.get(job.jobId) ?? job), ...rows.filter((row) => !held.has(row.jobId)).map((row) => refreshed.get(row.jobId) ?? mergeStatusOnImport([], [row])[0])]
}
