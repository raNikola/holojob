/**
 * The Kanban board of applications (docs/redesign/TRACKER_PLAN.md 3.2), as data. Pure: no I/O, no
 * clock (`today` is passed in). Cards come from the application store alone, never from the Jobs
 * list, so an application whose job left discovery still has its card.
 */

import { CLOSED_COLUMNS, FIRST_STAGE, UNFILED } from './applicationEnums.js'
import { daysInCurrentStage, foldApplication } from './foldApplication.js'
import { activeStages, boardColumn, labelFor, moveTargets } from './stageRegistry.js'

/** Days in a non-closed stage after which a card is marked stale (display only). */
export const STALE_AFTER_DAYS = 14

/** The board's columns in order: Applied, the active work stages, Rejected, Ghosted. */
export function boardColumns(settings) {
  return [FIRST_STAGE, ...activeStages(settings).map((s) => s.key), ...CLOSED_COLUMNS].map((key) => ({
    key,
    label: labelFor(key, settings),
  }))
}

/**
 * @returns {{ columns: {key, label, cards: object[]}[], closed: number, unfiled: number, total: number }}
 * `closed` counts open-outcome applications that are on no column (withdrawn, offer accepted ...),
 * `unfiled` those on a retired or unknown stage. Voided applications appear nowhere.
 */
export function buildBoard(store, settings, today) {
  const columns = boardColumns(settings).map((c) => ({ ...c, cards: [] }))
  const byKey = new Map(columns.map((c) => [c.key, c]))
  let closed = 0
  let unfiled = 0
  let total = 0
  for (const app of Object.values(store?.applications ?? {})) {
    const folded = foldApplication(app)
    const column = boardColumn(folded, settings)
    if (column === null) continue
    total += 1
    if (column === 'closed') closed += 1
    else if (column === UNFILED) unfiled += 1
    else {
      const days = daysInCurrentStage(folded, today)
      byKey.get(column)?.cards.push({
        appId: app.id,
        jobId: app.posting?.jobId ?? null,
        company: app.posting?.company || '',
        title: app.posting?.title || '',
        column,
        days,
        stale: !CLOSED_COLUMNS.includes(column) && days !== null && days > STALE_AFTER_DAYS,
      })
    }
  }
  // the longest wait first; a card with no known date goes last
  for (const column of columns) column.cards.sort((a, b) => (b.days ?? -1) - (a.days ?? -1) || (a.appId < b.appId ? -1 : 1))
  return { columns, closed, unfiled, total }
}

/** The "Move to" options for a card in `column`: every board column but its own. */
export function moveChoices(settings, column) {
  return moveTargets(settings).filter((key) => key !== column).map((key) => ({ value: key, label: labelFor(key, settings) }))
}

/** "3 closed · 1 unfiled", or '' when there is neither. */
export function boardFootnote({ closed, unfiled }) {
  return [closed && `${closed} closed (other outcomes)`, unfiled && `${unfiled} unfiled`].filter(Boolean).join(' · ')
}
