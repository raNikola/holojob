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

function notify() {
  window.dispatchEvent(new CustomEvent(JOB_ROUTE_EVENT))
}

/** Pushes a history entry, so Back returns to the view the click came from. */
export function openJobPage(jobId) {
  window.history.pushState({ holojobJob: true }, '', jobHash(jobId))
  notify()
}

/** Back when the page was opened from inside the app; otherwise (a deep link) drops the hash in place. */
export function closeJobPage() {
  if (window.history.state?.holojobJob) {
    window.history.back()
    return
  }
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  notify()
}
