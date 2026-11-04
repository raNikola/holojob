// The ad text of stored rows that the browser kept a shorter copy of (S8a). This is the ONE place where it is put back.
//
// `saveJobs` (jobStorage.js) may store the list without the ad text of some rows when the list outgrows the browser storage. Every reader of the
// list goes through `loadJobs()`, which calls `mergeCachedTexts` below, so a text that is in this cache is in every reader's rows at once:
// the search filter, the outreach providers, the AI context, the Jobs, Applications and Outreach screens. The cache is filled
//   1. by `saveJobs`, with the texts it is about to leave out (they are in memory at that moment), so one tab never loses a text it had; and
//   2. at start, by `hydrateJobTexts`, from the server's ledger, before any screen is shown (`JobTextGate`).
// Nothing here is stored in the browser: the cache lives and dies with the page.

export const TEXT_CACHE_MAX = 6000
export const TEXT_BATCH = 100
const HYDRATE_TIMEOUT_MS = 8000

const cache = new Map()

export const isBlank = (value) => !String(value ?? '').trim()

/** A row the browser keeps no text for and may have to get it back for: not a hand-entered job (its text is the owner's own and always stored). */
export const needsText = (job) => Boolean(job?.jobId) && !job.manualEntry && isBlank(job.description)

export function rememberTexts(jobs) {
  for (const job of jobs) {
    if (!job?.jobId || isBlank(job.description)) continue
    cache.delete(job.jobId) // newest last, so the oldest goes first past the bound
    cache.set(job.jobId, job.description)
  }
  while (cache.size > TEXT_CACHE_MAX) cache.delete(cache.keys().next().value)
}

/** The rows with the cached text put in where a row has none. The same array comes back when nothing was to be done. */
export function mergeCachedTexts(jobs) {
  if (!cache.size || !Array.isArray(jobs)) return jobs
  let changed = false
  const merged = jobs.map((job) => {
    if (!needsText(job) || !cache.has(job.jobId)) return job
    changed = true
    return { ...job, description: cache.get(job.jobId) }
  })
  return changed ? merged : jobs
}

export function rowsNeedingText(jobs) {
  return (jobs ?? []).filter((job) => needsText(job) && !cache.has(job.jobId))
}

/**
 * Asks the server's ledger for the ad text of `jobs`, 100 ids a request. Never throws: what could not be had is returned in `missing`
 * (the history was not reachable, or the ledger holds no text for that id), and the caller says so to the user.
 * @returns {Promise<{ requested: number, loaded: number, missing: string[] }>}
 */
export async function hydrateJobTexts(jobs, { fetchFn = globalThis.fetch, timeoutMs = HYDRATE_TIMEOUT_MS } = {}) {
  const wanted = [...new Set(rowsNeedingText(jobs).map((job) => job.jobId))]
  const missing = []
  let loaded = 0
  const deadline = Date.now() + timeoutMs
  for (let at = 0; at < wanted.length; at += TEXT_BATCH) {
    const ids = wanted.slice(at, at + TEXT_BATCH)
    const left = deadline - Date.now()
    if (left <= 0) { missing.push(...ids); continue }
    const controller = typeof AbortController === 'function' ? new AbortController() : null
    const timer = controller ? setTimeout(() => controller.abort(), left) : null
    try {
      const res = await fetchFn('/api/jobs/texts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobIds: ids }), signal: controller?.signal })
      const data = await res.json().catch(() => null)
      if (!res.ok || !data?.ok || typeof data.texts !== 'object' || !data.texts) throw new Error(`status ${res.status}`)
      for (const id of ids) {
        const text = data.texts[id]
        if (typeof text === 'string' && !isBlank(text)) {
          cache.set(id, text)
          loaded += 1
        } else missing.push(id)
      }
    } catch {
      missing.push(...ids)
    } finally {
      if (timer) clearTimeout(timer)
    }
  }
  while (cache.size > TEXT_CACHE_MAX) cache.delete(cache.keys().next().value)
  return { requested: wanted.length, loaded, missing }
}

/** For tests. */
export function resetJobTexts() {
  cache.clear()
}
