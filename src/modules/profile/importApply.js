// Applying a reviewed import draft to the stored profile (Wave 7). The effects are passed in, so every step and every failure can be tested
// without a browser or a server. Rules (docs/DECISIONS.md, "Wave 7"):
//   - parse and preview write nothing; this is the only place an import reaches the profile;
//   - a backup (server file) and a pre-import snapshot (browser) come first, and a failure of either aborts with nothing written;
//   - the profile is written once, as one object (the pure applyImportDraft), then pushed to the server mirror;
//   - a failed mirror sync is "not synced yet": retry resends the profile as it is stored and NEVER applies the import again;
//   - applying the same draft twice changes nothing (the second run computes the same profile and returns early, before any backup).

import { applyImportDraft, resolveChoices } from './importDraft.js'

/** Compare two profiles ignoring the save stamp, the only field every save changes. */
export function sameProfile(a, b) {
  const strip = (p) => JSON.stringify({ ...p, meta: { ...p?.meta, updatedAt: undefined } })
  return strip(a) === strip(b)
}

/**
 * @param {object} args
 * @param {object} args.profile the stored profile now
 * @param {object} args.draft the reviewed draft
 * @param {object} args.choices the review screen's choices
 * @param {File|null} [args.file] a PDF to store with the new My CVs entry (best effort)
 * @param {object} args.deps
 * @param {(profile: object) => Promise<boolean>} args.deps.backup server backup of the current profile; true when verified
 * @param {{ saveBefore: (profile: object) => void, saveAfter: (profile: object) => void, load: () => ({ before: object, after: object } | null), clear: () => void }} args.deps.snapshot
 *   the pre-import copy for Undo; saveBefore throws on failure (that aborts the import), saveAfter is best effort
 * @param {(file: File) => Promise<string|null>} [args.deps.upload] stores the PDF, answers its id
 * @param {(id: string) => Promise<void>} [args.deps.discardUpload] removes a stored PDF again
 * @param {(profile: object) => object} args.deps.commit writes the profile to the browser store and answers what was stored (throws on failure)
 * @param {(profile: object) => Promise<boolean>} args.deps.syncMirror pushes the profile to the server mirror; true when it arrived
 * @param {(pending: boolean) => void} args.deps.setSyncPending remembers that the mirror is behind
 * @param {() => void} [args.deps.markIntelligenceStale] tells the owner to regenerate the intelligence
 * @param {{ now?: Date, makeId?: () => string }} [args.options] passed to applyImportDraft
 * @returns {Promise<{ ok: boolean, applied: boolean, duplicate?: boolean, synced?: boolean, stage?: 'backup'|'snapshot'|'write', profile?: object }>}
 */
export async function applyReviewedImport({ profile, draft, choices, file = null, deps, options = {} }) {
  const resolved = resolveChoices(profile, draft, choices)
  const planned = applyImportDraft(profile, draft, resolved, options)
  if (sameProfile(planned, profile)) return { ok: true, applied: false, duplicate: true, synced: undefined, profile }

  const backedUp = await Promise.resolve().then(() => deps.backup(profile)).then((ok) => ok === true, () => false)
  if (!backedUp) return { ok: false, applied: false, stage: 'backup' }
  try { deps.snapshot.saveBefore(profile) } catch { return { ok: false, applied: false, stage: 'snapshot' } }

  let stored = null
  if (file && deps.upload) {
    try {
      const id = await deps.upload(file)
      if (id) stored = { id, filePath: `profile/cvs/${id}.pdf` }
    } catch { /* the entry is kept without a stored file */ }
  }
  const next = stored ? applyImportDraft(profile, draft, resolved, { ...options, file: stored }) : planned

  let saved
  try {
    saved = deps.commit(next)
  } catch {
    if (stored && deps.discardUpload) { try { await deps.discardUpload(stored.id) } catch { /* best effort */ } }
    return { ok: false, applied: false, stage: 'write' }
  }
  try { deps.snapshot.saveAfter(saved) } catch { /* Undo is then unavailable; the import itself stands */ }
  deps.markIntelligenceStale?.()
  deps.setSyncPending(true)
  const synced = await pushMirror(saved, deps)
  return { ok: true, applied: true, synced, profile: saved }
}

async function pushMirror(profile, deps) {
  const arrived = await Promise.resolve().then(() => deps.syncMirror(profile)).then((ok) => ok === true, () => false)
  deps.setSyncPending(!arrived)
  return arrived
}

/**
 * Resend the profile exactly as it is stored. This never reads a draft and never applies anything, so a retry after an interrupted
 * sync leaves the profile equal to one clean apply.
 * @returns {Promise<{ synced: boolean }>}
 */
export async function retryMirrorSync({ getProfile, deps }) {
  return { synced: await pushMirror(getProfile(), deps) }
}

/**
 * Undo the last import: put the pre-import copy back, only while nothing has changed since (the stored profile still equals the one
 * the import produced), so later edits are never thrown away.
 */
export async function undoLastImport({ getProfile, deps }) {
  const { snapshot } = deps
  const saved = snapshot.load()
  if (!saved || !sameProfile(getProfile(), saved.after)) return { ok: false, reason: saved ? 'changed' : 'none' }
  let restored
  try { restored = deps.commit(saved.before) } catch { return { ok: false, reason: 'write' } }
  snapshot.clear()
  deps.setSyncPending(true)
  const synced = await pushMirror(restored, deps)
  return { ok: true, synced }
}
