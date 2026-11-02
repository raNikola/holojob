// The full Job Details page lives at `#/jobs/<jobId>`; no router. App listens to `JOB_ROUTE_EVENT`, `popstate`
// and `hashchange`, so a deep link, the Back button and `openJobPage` all end in the same state.

export const JOB_ROUTE_EVENT = 'holojob:job-route'
const PREFIX = '#/jobs/'

/** The job id in a location hash, or null when the hash is not a job route. */
export function parseJobHash(hash) {
  if (typeof hash !== 'string' || !hash.startsWith(PREFIX)) return null
  const rest = hash.slice(PREFIX.length).replace(/\/$/, '')
  if (!rest || rest.includes('/')) return null
  try {
    const id = decodeURIComponent(rest)
    return id.trim() ? id : null
  } catch {
    return null
  }
}

export function jobHash(jobId) {
  return `${PREFIX}${encodeURIComponent(jobId)}`
}

/** `found` with the job, or `missing` for an id the job list does not hold (a stale link, a cleared list). */
export function findRoutedJob(jobs, jobId) {
  const job = Array.isArray(jobs) ? jobs.find((j) => j.jobId === jobId) : undefined
  return job ? { status: 'found', job } : { status: 'missing', jobId }
}

/** The full page opens a stored job, or one with a fallback: an application for it, or a ledger entry (`jobResolve.js`). */
export const canOpenJobPage = (storedJob, { hasFallback = false } = {}) => Boolean(storedJob) || hasFallback
export const MISSING_JOB_HINT = 'This posting is no longer in your jobs list'

/**
 * Where opening an application goes: the quick view on its browser row, else Job Details by job id, which needs no row.
 * An application saved with no job id has no route.
 */
export function applicationOpenTarget(jobs, jobId) {
  if (!jobId) return { kind: 'none' }
  const job = (jobs ?? []).find((j) => j.jobId === jobId)
  return job ? { kind: 'drawer', job } : { kind: 'page', jobId }
}

function notify() {
  window.dispatchEvent(new CustomEvent(JOB_ROUTE_EVENT))
}

/** Pushes a history entry, so Back returns to the view the click came from. */
export function openJobPage(jobId) {
  window.history.pushState({ holojobJob: true }, '', jobHash(jobId))
  notify()
}

/** `back` when this history entry was pushed by `openJobPage` (the previous entry is the view it came from); otherwise `replace`. */
export function closeMode(historyState) {
  return historyState?.holojobJob ? 'back' : 'replace'
}

/** Back when the page was opened from inside the app; otherwise (a deep link, an edited hash) drops the hash in place. */
export function closeJobPage() {
  if (closeMode(window.history.state) === 'back') {
    window.history.back()
    return
  }
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  notify()
}
