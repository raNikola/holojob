/**
 * Reset the profile on disk without deleting it: the profile mirror, the stored CVs
 * and the candidate intelligence are copied into a timestamped folder next to
 * data/profile, checked, and only then removed. Jobs, applications, AI data, secrets
 * and config are never touched. A failed backup leaves everything where it was.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE } from './atomic-file.js'
import { isSecretPath } from './secret-paths.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')

export const RESET_CONFIRM_WORD = 'RESET'

// Fixed answers: nothing read from the profile, the disk or an exception ever goes into one.
export const RESET_ERRORS = {
  not_confirmed: { status: 400, error: 'Type RESET to confirm the reset.' },
  backup_failed: { status: 500, error: 'The backup could not be made, so nothing was removed.' },
  remove_failed: { status: 500, error: 'The backup was made but the old files could not all be removed. Try again.' },
}

// What a reset moves, relative to data/. The profile folder keeps its .gitkeep.
const INTELLIGENCE_FILE = 'candidate-intelligence.json'
const KEEP_IN_PROFILE = new Set(['.gitkeep'])

export function backupFolderName(now = new Date()) {
  const p = (n, w = 2) => String(n).padStart(w, '0')
  return `profile.bak-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`
}

function uniqueDir(dataDir, name) {
  let candidate = name
  for (let i = 2; fs.existsSync(path.join(dataDir, candidate)); i += 1) candidate = `${name}-${i}`
  return candidate
}

function listTargets(dataDir) {
  const targets = []
  const profileDir = path.join(dataDir, 'profile')
  if (fs.existsSync(profileDir)) {
    for (const name of fs.readdirSync(profileDir)) {
      if (!KEEP_IN_PROFILE.has(name)) targets.push({ rel: `profile/${name}`, abs: path.join(profileDir, name) })
    }
  }
  const intel = path.join(dataDir, 'intelligence', INTELLIGENCE_FILE)
  if (fs.existsSync(intel)) targets.push({ rel: `intelligence/${INTELLIGENCE_FILE}`, abs: intel })
  return targets
}

function sizeOf(abs) {
  const stat = fs.statSync(abs)
  if (!stat.isDirectory()) return stat.size
  return fs.readdirSync(abs).reduce((sum, name) => sum + sizeOf(path.join(abs, name)), 0)
}

/** cpSync carries each source's mode over; the copy inside the private backup folder gets 600 / 700. Links are skipped. */
function makePrivate(dir, fsImpl) {
  for (const entry of fsImpl.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      fsImpl.chmodSync(abs, PRIVATE_DIR_MODE)
      makePrivate(abs, fsImpl)
    } else if (entry.isFile()) {
      fsImpl.chmodSync(abs, PRIVATE_FILE_MODE)
    }
  }
}

/**
 * @param {{ dataDir?: string, now?: Date, fsImpl?: object }} [options] dataDir and fsImpl exist for tests.
 * @returns {{ ok: true, backup: string|null, moved: number } | { ok: false, code: string }}
 */
export function resetProfileOnDisk({ dataDir = path.join(ROOT, 'data'), now = new Date(), fsImpl = fs } = {}) {
  let targets
  try {
    targets = listTargets(dataDir)
  } catch {
    return { ok: false, code: 'backup_failed' }
  }
  // Nothing on disk: already reset. No backup folder is made for an empty profile.
  if (targets.length === 0) return { ok: true, backup: null, moved: 0 }

  const folder = uniqueDir(dataDir, backupFolderName(now))
  const backupDir = path.join(dataDir, folder)
  try {
    fsImpl.mkdirSync(backupDir, { recursive: false, mode: PRIVATE_DIR_MODE })
    for (const target of targets) {
      const dest = path.join(backupDir, target.rel)
      fsImpl.mkdirSync(path.dirname(dest), { recursive: true, mode: PRIVATE_DIR_MODE })
      // Credentials are never copied, whatever they are named (secret-paths.js is the one list).
      fsImpl.cpSync(target.abs, dest, {
        recursive: true,
        filter: (src) => !isSecretPath(`data/${path.relative(dataDir, src).split(path.sep).join('/')}`),
      })
      if (sizeOf(dest) !== sizeOf(target.abs)) throw new Error('size mismatch')
    }
    makePrivate(backupDir, fsImpl)
  } catch {
    try { fsImpl.rmSync(backupDir, { recursive: true, force: true }) } catch { /* the originals are untouched either way */ }
    return { ok: false, code: 'backup_failed' }
  }

  try {
    for (const target of targets) fsImpl.rmSync(target.abs, { recursive: true, force: true })
  } catch {
    return { ok: false, code: 'remove_failed' }
  }
  return { ok: true, backup: folder, moved: targets.length }
}

// The route calls through this seam so route tests never touch the real data/ folder.
let runner = resetProfileOnDisk
export function setProfileResetRunner(fn) { runner = fn ?? resetProfileOnDisk }
export const runProfileReset = (...args) => runner(...args)
