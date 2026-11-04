// The live view of a running run (S7c), as pure functions: what to show from the record and the events the API returned.
import { formatDuration, show, sourceStatusLabel } from './runView.js'

export const CANCEL_REQUESTED_TEXT = 'Cancel requested. The run stops at its next safe point.'
export const CANCEL_CONFIRM_TEXT = 'Cancel this run? The ads it has already collected are saved and nothing else changes. Scoring is skipped.'
const PENDING = '–'

/** The source rows of a running run: the record's rows, and the sources the events say are being read or just ended. */
export function liveSourceRows(run, events) {
  const rows = new Map()
  for (const source of run?.sources ?? []) {
    rows.set(source.name, { name: source.name, state: sourceStatusLabel(source.status), reading: false, returned: show(source.returned), collected: show(source.collected) })
  }
  for (const event of events ?? []) {
    if (!event.source) continue
    if (event.type === 'source_start' && !rows.has(event.source)) rows.set(event.source, { name: event.source, state: 'Reading…', reading: true, returned: PENDING, collected: PENDING })
    if (event.type === 'source_end' && !(run?.sources ?? []).some((one) => one.name === event.source)) {
      rows.set(event.source, { name: event.source, state: sourceStatusLabel(event.status), reading: false, returned: show(event.read), collected: show(event.kept) })
    }
  }
  return [...rows.values()]
}

/** "Running for 2 min 10 s", as of `receivedAt` (the time of the last answer), so it moves only when the page hears from the server. */
export function elapsedText(run, receivedAt) {
  const started = run?.startedAt ? Date.parse(run.startedAt) : NaN
  if (Number.isNaN(started) || !receivedAt) return null
  return `Running for ${formatDuration(Math.max(0, Math.round((receivedAt - started) / 1000)))}`
}

/** Which step the run is in, from the record's steps. */
export function currentStepText(run) {
  const step = (run?.steps ?? []).find((one) => one.status === 'running')
  if (!step) return null
  return step.name === 'scoring' ? 'Scoring the jobs' : 'Reading the sources'
}

/**
 * What the server's answer to a cancel request means for the screen. `requested`: the request is on file and the run is still going, so nothing
 * is claimed about it stopping. `settled`: the run was not (or is no longer) running, so the screen refreshes. `refused`: nothing happened.
 */
export function classifyCancel({ status, body }) {
  if (status === 202 || body?.result === 'cancel_already_requested') return { kind: 'requested', message: CANCEL_REQUESTED_TEXT }
  if (status === 200) return { kind: 'settled', message: body?.message || 'This run is no longer running. Nothing changed.' }
  return { kind: 'refused', message: body?.message || `The cancel was not accepted (status ${status}). Nothing changed.` }
}
