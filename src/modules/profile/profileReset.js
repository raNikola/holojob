import { clearProfile } from '../../utils/storage.js'
import { buildExportProfile } from '../../utils/exportJson.js'
import { buildIntelligenceExport, clearIntelligence } from '../intelligence/intelligenceExport.js'

export const RESET_WORD = 'RESET'
export const RESET_ENDPOINT = '/api/profile/reset'

// Shown in the confirm dialog. One list, so the dialog and the tests cannot drift apart.
export const RESET_REMOVES = [
  'Basic info: name, e-mail, phone, location, current role, years, target roles, salary, languages, work authorization.',
  'Questionnaire answers, including answers filled in from your résumé.',
  'Résumé text and parsed data, and the CV library (its entries and the stored PDF files on the server).',
  'Candidate intelligence generated from them, including your scoring weights, which go back to the defaults.',
  'Onboarding flags: onboarding complete, finished early, the Complete your profile dismissal, and the saved step.',
]
export const RESET_KEEPS = [
  'Jobs and scores, the pipeline state and the job store on the server.',
  'Applications and the tracker, including the CV recorded on each application (its link to the library entry will point to a CV that is in the backup folder).',
  'Findings store, AI budget, AI provider settings and the usage ledger.',
  'API keys, the LinkedIn cookie and every other secret.',
  'Board columns, tracking settings and other Settings.',
  'Project intelligence from repository scans.',
]

export const isResetConfirmed = (text) => text === RESET_WORD
export const canRunReset = (text, running) => isResetConfirmed(text) && !running

// Fixed texts, keyed by the code the server answers with. Nothing from a response body is shown.
const FAILURES = {
  not_confirmed: 'Type RESET to confirm the reset.',
  backup_failed: 'The backup could not be made, so nothing was removed.',
  remove_failed: 'The backup was made but the old files could not all be removed. Your browser profile was left as it is; try again.',
}
const GENERIC_FAILURE = 'The reset did not run and nothing was removed.'

/**
 * Only what the browser already holds, never a secret: the profile as it is synced to the server and the
 * intelligence file. The stored CV PDFs are not in it; they are in the server's backup folder.
 */
export function buildProfileBackup(profile, intelligence, now = new Date()) {
  return {
    kind: 'holojob-profile-backup',
    exportedAt: now.toISOString(),
    profile: buildExportProfile(profile),
    intelligence: intelligence ? buildIntelligenceExport(intelligence) : null,
  }
}

export function backupFileName(now = new Date()) {
  return `holojob-profile-backup-${now.toISOString().replace(/[:.]/g, '-')}.json`
}

/**
 * Ask the server to back up and remove the profile files, and only when it says ok clear the profile and
 * intelligence keys in this browser. A server that is unreachable or fails leaves the browser as it was, so a
 * failed reset never loses the profile.
 */
export async function requestProfileReset(confirmText, { fetchImpl = globalThis.fetch } = {}) {
  if (!isResetConfirmed(confirmText)) return { ok: false, error: FAILURES.not_confirmed }
  let body
  try {
    const res = await fetchImpl(RESET_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: RESET_WORD }),
    })
    body = await res.json().catch(() => null)
    if (!res.ok || body?.ok !== true) return { ok: false, error: FAILURES[body?.code] ?? GENERIC_FAILURE }
  } catch {
    return { ok: false, error: GENERIC_FAILURE }
  }
  clearProfile()
  clearIntelligence()
  return { ok: true, backup: typeof body.backup === 'string' ? body.backup : null }
}

// Settings unmounts when the reset sends the user to onboarding, so the success text waits here for the next screen.
let pendingNotice = null
export function setResetNotice(text) { pendingNotice = text }
export function takeResetNotice() {
  const text = pendingNotice
  pendingNotice = null
  return text
}
