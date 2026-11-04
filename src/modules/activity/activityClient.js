// GET /api/runs (S7a). The Activity screen reads the run history and nothing else; it keeps no copy of it in the browser.

export const PAGE_SIZE = 30

/** One page of runs, newest first. `before` is the `next` of the page before. Throws with a sentence a user can read. */
export async function fetchRuns({ before = null, limit = PAGE_SIZE, fetchFn = globalThis.fetch } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before) params.set('before', before)
  let res
  try {
    res = await fetchFn(`/api/runs?${params}`)
  } catch {
    throw new Error('The server could not be reached.')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok || !data?.ok || !Array.isArray(data.runs)) throw new Error(`The run history is not available (status ${res.status}).`)
  return data
}

/**
 * One run and its events from line `after` on (S7c). A 404 means the run is not there (any more): the error carries `status`.
 * Any other failure is a plain error the poller retries.
 */
export async function fetchRun(runId, after = 0, { fetchFn = globalThis.fetch } = {}) {
  let res
  try {
    res = await fetchFn(`/api/runs/${encodeURIComponent(runId)}?after=${after}`)
  } catch {
    throw new Error('The server could not be reached.')
  }
  const data = await res.json().catch(() => null)
  if (!res.ok || !data?.ok || !data.run) throw Object.assign(new Error(data?.message || `The run is not available (status ${res.status}).`), { status: res.status })
  return data
}

/** POST /api/rescrape/cancel. Resolves with { status, body } for every answer the server gives; rejects only when it cannot be reached. */
export async function cancelRun(runId, { fetchFn = globalThis.fetch } = {}) {
  let res
  try {
    res = await fetchFn('/api/rescrape/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ runId }) })
  } catch {
    throw new Error('The server could not be reached.')
  }
  const body = await res.json().catch(() => ({}))
  return { status: res.status, body }
}
