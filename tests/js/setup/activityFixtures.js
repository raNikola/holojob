// Run records as the API would show them: built with the real `project()` from scripts/run-history.js, so a fixture cannot drift from the API.
import { project } from '../../../scripts/run-history.js'

export const start = (n) => `2026-11-${String(1 + Math.floor(n / 24)).padStart(2, '0')}T${String(n % 24).padStart(2, '0')}:00:00+00:00`

export function record(n, extra = {}) {
  return {
    version: 1, runId: `run${String(n).padStart(4, '0')}`, trigger: 'manual', startedAt: start(n), finishedAt: start(n).replace(':00:00', ':20:00'), status: 'ok',
    sources: [{ name: 'jobspy', status: 'ok', read: 100, kept: 40, new: 3, error: null, boardsFailed: [], skipReason: null }],
    issues: [], steps: [{ name: 'discovery', status: 'ok', exitCode: 0 }, { name: 'scoring', status: 'ok', exitCode: 0 }], staging: { ok: true, problems: [] },
    ...extra,
  }
}

export const proven = (name = 'jobspy') => ({ name, proof: { proven: true, why: ['proven'], boards: [] }, filterReasons: { title_not_matched: 60 } })
export const importBlock = (extra = {}) => ({
  kind: 'complete', complete: true, saved: 45, new: 3, refreshed: 42, duplicatesRemoved: 5, crosspostsMerged: 1, rejected: 0,
  ledger: { closed: 1, absent: 2, reopened: 0, changed: 4, known: 42 }, sources: [proven()], ...extra,
})

/** The API's answer for these records. */
export function answer(records, { next = null, alive = true } = {}) {
  return { ok: true, runs: records.map((one) => project(one, { alive })), next, skipped: 0, retentionDays: 90, activeRunId: null }
}

export const api = (records, options) => ({ status: 200, body: answer(records, options) })

/** A fetch that answers from a queue of { status, body } (or an Error to reject with), and remembers its calls. */
export function fakeFetch(...queue) {
  const calls = []
  const fn = async (url) => {
    calls.push(url)
    const next = queue.length > 1 ? queue.shift() : queue[0]
    if (next instanceof Error) throw next
    return { ok: next.status >= 200 && next.status < 300, status: next.status, json: async () => next.body }
  }
  fn.calls = calls
  return fn
}

// --- live view (S7c) --------------------------------------------------------------------------------------------------------------

import { projectEvent } from '../../../scripts/run-history.js'

/** A running Re-scrape record. */
export const running = (n = 9, extra = {}) => record(n, {
  status: 'running', finishedAt: null, orchestrator: 'rescrape', sources: [], steps: [{ name: 'discovery', status: 'running', exitCode: null }], ...extra,
})

/** What GET /api/runs/<id> answers: built with the real projections. */
export function liveBody(rec, { events = [], next = events.length, alive = true, cancelRequested = false } = {}) {
  const run = project(rec, { alive, cancelRequested })
  return { ok: true, run, events: events.map(projectEvent), next, active: run.status === 'running' }
}
export const live = (rec, options) => ({ status: 200, body: liveBody(rec, options) })

export const ev = (type, extra = {}) => ({ type, at: '2026-11-01T09:00:00+00:00', ...extra })

/**
 * A fetch that routes like the server: the list, one run, and the cancel route. Each responder is a function of the call, so a test can change what
 * the server says between polls. Every call is recorded with its method and body.
 */
export function fakeServer({ list, live: liveResponder, cancel } = {}) {
  const calls = []
  const fn = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? 'GET', body: init.body, headers: init.headers })
    let reply
    if (url.startsWith('/api/rescrape/cancel')) reply = await (cancel ? cancel(JSON.parse(init.body), calls) : { status: 202, body: { ok: true, result: 'cancel_requested' } })
    else if (/^\/api\/runs\/[^?]+/.test(url)) reply = await (liveResponder ? liveResponder(url, calls) : { status: 404, body: { ok: false } })
    else reply = await (list ? list(url, calls) : api([]))
    if (reply instanceof Error) throw reply
    return { ok: reply.status >= 200 && reply.status < 300, status: reply.status, json: async () => reply.body }
  }
  fn.calls = calls
  fn.count = (pattern) => calls.filter((call) => pattern.test(`${call.method} ${call.url}`)).length
  return fn
}
