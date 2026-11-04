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
