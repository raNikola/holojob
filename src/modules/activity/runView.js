// What the Activity screen says about a run, in one place. Pure: the API's answer in, words out. It shows what the API returned and
// invents nothing: a value the API says is null is "Not recorded", never 0, and a proof the record never held is not "Not proven".
import reasons from '../../data/proofReasons.json'
import { cancelledText } from '../jobs/rescrapeRun.js'

export const NOT_RECORDED = 'Not recorded'

export const STATUS_LABELS = {
  ok: 'OK', partial: 'Partial', failed: 'Failed', skipped: 'Skipped', running: 'Running', interrupted: 'Interrupted', cancelled: 'Cancelled', unknown: 'Unknown',
}
export const STATUS_TONES = { ok: 'high', partial: 'medium', failed: 'warn', skipped: 'low', running: 'derived', interrupted: 'warn', cancelled: 'medium', unknown: 'low' }
export const TRIGGER_LABELS = { manual: 'Manual', pipeline: 'Pipeline', scheduled: 'Scheduled', unknown: 'Unknown' }
export const SOURCE_STATUS_LABELS = { ok: 'OK', partial: 'Partly read', failed: 'Failed', skipped: 'Skipped', unfinished: 'Unfinished', unknown: 'Unknown' }
export const SOURCE_STATUS_TONES = { ok: 'high', partial: 'medium', failed: 'warn', skipped: 'low', unfinished: 'medium', unknown: 'low' }

/** The six numbers, each with its one-line help. The same words are used wherever a number is named. */
export const NUMBER_HELP = [
  ['Returned', 'Ads the source gave us, before your search rules were applied.'],
  ['Filtered out', 'Returned ads your search rules dropped (role, location, country).'],
  ['Collected', 'Ads that passed your rules and were written to staging.'],
  ['Saved', 'Ads written to your list: collected, whole, and not duplicates. It includes ads you already had.'],
  ['New', 'Saved ads that were never seen before.'],
  ['Refreshed', 'Saved ads you already had, seen again.'],
]
export const SOURCE_NEW_NOTE = 'Per-source "New" is counted after duplicates are merged, under the source of the copy that was kept, so the sources\' "New" do not add up to the run\'s "New".'
export const PROOF_HELP = '"Proven" means this run may count toward Stale and, for a board, toward closing an ad. It does not mean the run was good.'
export const RETENTION_NOTE = 'Records older than 90 days are removed, and the run history is not part of a backup.'

/** A count the API gave, or "Not recorded". null and undefined are never a number. */
export function show(value) {
  return Number.isFinite(value) ? value.toLocaleString() : NOT_RECORDED
}

export function formatTime(iso) {
  const date = iso ? new Date(iso) : null
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : NOT_RECORDED
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return NOT_RECORDED
  if (seconds < 60) return `${seconds} s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`
}

export const statusLabel = (status) => STATUS_LABELS[status] ?? STATUS_LABELS.unknown
export const triggerLabel = (trigger) => TRIGGER_LABELS[trigger] ?? TRIGGER_LABELS.unknown
export const sourceStatusLabel = (status) => SOURCE_STATUS_LABELS[status] ?? SOURCE_STATUS_LABELS.unknown

/** "Saved 455 (3 new, 452 already known and refreshed)". A cancelled run adds that nothing else changed. */
export function savedText(run) {
  const { saved, new: added, refreshed } = run.counts
  const tail = run.status === 'cancelled' ? '. Nothing else changed.' : ''
  // The cancel outcome itself says nothing was saved (the step had to be killed, or the cancel came before anything was collected).
  if (!Number.isFinite(saved) && run.status === 'cancelled' && run.cancel?.outcome === 'stopped_nothing_imported') return `Nothing was saved${tail}`
  if (!Number.isFinite(saved)) return `Saved: ${NOT_RECORDED}`
  const parts = Number.isFinite(added) && Number.isFinite(refreshed) ? ` (${added.toLocaleString()} new, ${refreshed.toLocaleString()} already known and refreshed)` : ''
  return `Saved ${saved.toLocaleString()}${parts}${tail}`
}

/** The short form for a run's row: "455 (3 new)". */
export function savedShort(run) {
  const { saved, new: added } = run.counts
  if (!Number.isFinite(saved)) return NOT_RECORDED
  return Number.isFinite(added) ? `${saved.toLocaleString()} (${added.toLocaleString()} new)` : saved.toLocaleString()
}

/** The sentence under a run's badge when the badge alone does not say enough. Null when it does. */
export function statusSentence(run) {
  switch (run.status) {
    case 'cancelled':
      return cancelledText(run.cancel ? { ...run.cancel, saved: run.cancel.saved ?? run.counts.saved } : undefined)
    case 'interrupted':
      return run.inferred
        ? 'The record says this run was still going, but nothing is holding the run lock, so it stopped without finishing. It is not resumed.'
        : 'This run stopped without finishing (it was killed, or the server restarted). It is not resumed.'
    case 'skipped':
      return 'Every source was skipped, so nothing was searched.'
    case 'failed':
      return run.import?.nothingSaved === 'no_usable_source' ? 'No source gave a usable result, so nothing was imported and the job list was not changed.' : 'This run failed. The issues below say where.'
    case 'partial':
      return 'Some sources did not finish or did not read everything. The sources below say which.'
    case 'running':
      return 'This run is in progress. Refresh to see where it is.'
    default:
      return run.cancel?.outcome === 'imported_before_cancel' ? 'The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped.' : null
  }
}

/** The reason code as words. A code this build has no text for is shown as itself, never as nothing. */
export function reasonText(code) {
  return reasons[code]?.text || `Reason code: ${code}`
}

/** A proof as the screen shows it: one of three states, and the reasons. */
export function proofView(proof) {
  // Only the two states the API names are claims; anything else, including no data, is Not recorded and never Not proven.
  if (!proof || (proof.state !== 'proven' && proof.state !== 'not_proven')) return { state: 'not_recorded', label: NOT_RECORDED, tone: 'low', lines: [] }
  const lines = (proof.codes ?? []).map(reasonText)
  if (proof.state === 'proven') return { state: 'proven', label: 'Proven', tone: 'high', lines }
  return { state: 'not_proven', label: 'Not proven', tone: 'medium', lines: lines.length ? lines : ['Not proven (the reason was not recorded)'] }
}

/** The complete-read line of a source whose listing read is checked without being used to close ads. Null when nothing was recorded. */
export function completeReadText(read) {
  if (!read || typeof read !== 'object') return null
  if (read.complete === true) return 'Listing read in full (the number of ads read equals the total the site reports). Not used to close ads yet.'
  const why = (read.codes ?? []).map(reasonText).join('; ')
  return `Listing not proven complete${why ? `: ${why}` : ''}. Not used to close ads yet.`
}

const FILTER_LABELS = {
  title_not_matched: "Title didn't match", search_terms_not_matched: "Search terms didn't match", location_not_matched: "Location didn't match",
  country_not_matched: "Country didn't match", not_listed: "Not listed on the company's board", no_detail_text: 'Full ad text could not be read',
  detail_cap: 'Full ad text not read: over the limit for one run', title_excluded: 'Title had an excluded word', other: 'Other reasons',
}
const humanise = (code) => `${code.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())}`

/** The biggest reasons a source's ads were filtered out: "Title didn't match: 400, Location didn't match: 22 and 1 more". */
export function filterReasonText(reasonCounts, limit = 3) {
  if (!reasonCounts) return NOT_RECORDED
  const entries = Object.entries(reasonCounts).sort((a, b) => b[1] - a[1])
  if (!entries.length) return null
  const top = entries.slice(0, limit).map(([code, number]) => `${FILTER_LABELS[code] ?? humanise(code)}: ${number.toLocaleString()}`)
  return entries.length > limit ? `${top.join(', ')} and ${entries.length - limit} more` : top.join(', ')
}

const STEP_LABELS = { ok: 'Finished', failed: 'Failed', running: 'Running', cancelled: 'Cancelled', interrupted: 'Interrupted', skipped: 'Skipped', partial: 'Partial', unknown: 'Unknown' }

/** What happened to scoring in this run, from the steps the API returned. */
export function scoringText(run) {
  const step = run.steps.find((one) => one.name === 'scoring')
  if (step) return STEP_LABELS[step.status] ?? STEP_LABELS.unknown
  if (run.status === 'cancelled') return 'Skipped because the run was cancelled'
  if (run.cancel?.outcome === 'imported_before_cancel') return 'Skipped because the cancel came after the jobs were saved'
  const discovery = run.steps.find((one) => one.name === 'discovery')
  if (discovery && discovery.status !== 'ok') return 'Not run, because discovery did not finish'
  return NOT_RECORDED
}

export function stagingText(run) {
  const parts = []
  if (run.staging.ok === true) parts.push('Saved correctly')
  else if (run.staging.ok === false) parts.push('Staging failed: this run was not fully saved')
  else parts.push(NOT_RECORDED)
  if (run.incompleteCommit) parts.push('A save of the job files was left incomplete')
  return parts.join('. ')
}

/** The ledger effect, in words. Only an ordinary import closes or marks anything; a cancelled run changes nothing but what it saved. */
export function ledgerText(run) {
  if (!run.import) return NOT_RECORDED
  if (run.import.kind === 'partial') return 'Nothing else changed: no ad was closed, marked absent or reopened.'
  if (run.import.kind === 'nothing') return run.import.nothingSaved === 'no_usable_source' ? 'No source gave a usable result, so nothing was imported and the job list was not changed.' : 'Nothing was saved, so nothing changed.'
  if (run.import.kind === 'refused') return 'The import was refused, so nothing changed.'
  const ledger = run.import.ledger
  if (!ledger) return NOT_RECORDED
  const closed = Number.isFinite(ledger.closed) ? ledger.closed : null
  const absent = Number.isFinite(ledger.absent) ? ledger.absent : null
  const reopened = Number.isFinite(ledger.reopened) ? ledger.reopened : null
  const base = [['closed', closed], ['marked absent', absent], ['reopened', reopened]].map(([word, number]) => `${number === null ? NOT_RECORDED : number.toLocaleString()} ${word}`).join(', ')
  const held = heldText(run.import.held)
  return held ? `${base}. ${held}` : base
}

const HELD_LABELS = [
  ['keptFailedBoard', 'kept open because its board failed'],
  ['keptEmptyBoard', 'kept open because its board answered empty'],
  ['keptSourceNotRun', 'kept open because its source did not run'],
  ['keptUnproven', 'kept open because the read was not proven complete'],
  ['keptBoardNotRead', 'kept open because its board was not read'],
  ['listedButFiltered', 'still listed but dropped by a filter'],
]

/** Why ads were not closed, in words. Empty when the run recorded nothing or every count is zero. */
export function heldText(held) {
  if (!held) return ''
  return HELD_LABELS.filter(([key]) => Number.isFinite(held[key]) && held[key] > 0).map(([key, label]) => `${held[key].toLocaleString()} ${label}`).join(', ')
}
