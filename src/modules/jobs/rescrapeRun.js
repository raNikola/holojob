// The background Re-scrape in the browser: start it, read its status. The run lives on the server; this only follows it.
import { syncManualJobs } from './manualScoring.js'

/** Starts a run on the server. Hand-entered jobs go over first, so this run scores them. Throws with the server's reason. */
export async function startRescrapeRun({ providers, country, intelligence, profile }, { fetchFn = globalThis.fetch, sync = syncManualJobs } = {}) {
  await sync()
  const res = await fetchFn('/api/rescrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ providers, country, intelligence, profile }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.message || data.error || 'Re-scrape did not start')
  return data
}

export async function fetchRescrapeStatus(after = 0, { fetchFn = globalThis.fetch } = {}) {
  const res = await fetchFn(`/api/rescrape/status?after=${after}`)
  if (!res.ok) throw new Error(`Re-scrape status unavailable (${res.status})`)
  return res.json()
}

export function emptyRunView() {
  return { run: null, active: false, cancelRequested: false, events: [], next: 0, incompleteCommit: null, scoringBehind: false, reread: false }
}

/**
 * The view after one status answer. Its events are from the cursor of the run the view was following: an answer about another
 * run starts over with `reread` set, and the caller asks again from line 0.
 */
export function applyStatus(view, status) {
  const shared = { run: status.run ?? null, active: Boolean(status.active), cancelRequested: Boolean(status.cancelRequested), incompleteCommit: status.incompleteCommit ?? null, scoringBehind: Boolean(status.scoringBehind) }
  const switched = view.run && status.run && view.run.runId !== status.run.runId && view.next > 0
  if (switched) return { ...shared, events: [], next: 0, reread: true }
  return { ...shared, events: [...view.events, ...(status.events ?? [])], next: status.next ?? view.next, reread: false }
}

const STEP_NAMES = { discovery: 'Discovery', scoring: 'Scoring' }

/** One event in words. A kind this build does not know is shown by name rather than hidden. */
export function eventText(event) {
  const step = STEP_NAMES[event.step] ?? event.step
  switch (event.type) {
    case 'run_start': return 'Run started'
    case 'run_end': return `Run finished: ${event.status}`
    case 'step_start': return `${step} started`
    case 'step_end': return event.status === 'ok' ? `${step} finished` : event.status === 'cancelled' ? `${step} cancelled` : `${step} failed`
    case 'step_skipped': return `${step} skipped`
    case 'cancel_requested': return 'Cancel requested'
    case 'cancel_signal': return `Stopping ${step}`
    case 'cancel_kill': return `${step} did not stop in time and was ended`
    case 'scrape_stopped': return 'Scraping stopped'
    case 'cancelled': return event.imported ? `Cancelled: ${event.imported} collected ads imported, held` : 'Cancelled: nothing was imported'
    case 'source_start': return `Reading ${event.source}`
    case 'source_end':
      if (event.error) return `${event.source}: ${event.status}, ${event.error}`
      if (event.skipReason) return `${event.source}: ${event.status}, ${event.skipReason}`
      return `${event.source}: ${event.status}, ${event.kept} kept of ${event.read} read`
    case 'commit_start': return 'Saving the job files'
    case 'commit_end': return 'Job files saved'
    default: return event.message ?? event.type
  }
}

export function latestEventText(view) {
  const last = view.events[view.events.length - 1]
  return last ? eventText(last) : ''
}
