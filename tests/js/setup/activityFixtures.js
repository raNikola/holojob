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
