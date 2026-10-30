/**
 * The Job boards section of Settings > Sources: labels and the draft logic. Pure; the panel renders it.
 * The list of sources and which are opt-in come from the server (source_definitions.py), never from here.
 */

export const BOARD_LABELS = {
  jobspy: 'LinkedIn (JobSpy)',
  infostud: 'Infostud',
  workable: 'Workable',
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
  wellfound: 'Wellfound',
  remoteok: 'RemoteOK',
  yc: 'YC Work at a Startup',
  wwr: 'We Work Remotely',
  joberty: 'Joberty',
}

export const BOARD_SUBTEXT = {
  joberty: 'Serbian IT board · Product Management',
}

export const BOARD_HELP = {
  joberty: "Reads Joberty's public API (Product Management category). Their terms (sections 7 and 8) restrict commercial and unauthorized use; check them before enabling.",
}

export const CONSENT_LABEL = 'I have read the terms'

export function boardLabel(name) {
  return BOARD_LABELS[name] || name
}

/** { name: active } for the opt-in boards, as the server holds them. */
export function draftFrom(boards) {
  return Object.fromEntries((boards || []).filter((b) => b.optIn).map((b) => [b.name, b.active === true]))
}

/** Opt-in boards the draft switches on that the server has off: each needs the consent line. */
export function turningOn(draft, boards) {
  const saved = draftFrom(boards)
  return Object.keys(draft).filter((name) => draft[name] && !saved[name])
}

/** The PUT body for what changed, or null when nothing did. */
export function changesFrom(draft, boards, consent = {}) {
  const saved = draftFrom(boards)
  const changed = Object.keys(draft).filter((name) => draft[name] !== saved[name])
  if (changed.length === 0) return null
  return Object.fromEntries(changed.map((name) => [name, draft[name]
    ? { active: true, consentAccepted: consent[name] === true }
    : { active: false }]))
}

export function canSave(draft, boards, consent = {}) {
  return changesFrom(draft, boards, consent) !== null && turningOn(draft, boards).every((name) => consent[name] === true)
}

function day(iso) {
  return iso ? String(iso).slice(0, 10) : ''
}

/** One line about an opt-in board's consent record, or '' before any. */
export function consentSummary(board) {
  if (!board?.consentAcceptedAt) return ''
  const parts = [`Terms accepted ${day(board.consentAcceptedAt)}`]
  if (board.migratedFrom) parts.push('moved from the old Jobs-screen checkbox')
  if (!board.active && board.disabledAt) parts.push(`switched off ${day(board.disabledAt)}`)
  return parts.join(' · ')
}
