/**
 * Automatic backup of the four owner files, immediately before any write that changes them (owner decision 2026-11-23).
 *
 *   data/backups/auto/<file name>/<YYYYMMDD-HHMMSS>.json     (UTC; files 600, folders 700; read back and hash-checked)
 *
 * Files: candidate-intelligence.json, candidate-profile.json, profile-enrichment.json, scored_jobs.json. Nothing else.
 * Kept: the last 10 versions per file, the last 3 for scored_jobs.json; older ones are removed here, after a successful backup.
 * A file that does not exist yet has nothing to back up. New content equal to the current content (the profile ignoring its
 * `meta.updatedAt`, which every save refreshes) makes no backup. When the backup cannot be written, `BackupError` is thrown and the
 * caller must not write. Restore is manual: copy a version back over the file (docs/ARCHITECTURE.md, "Automatic backups").
 *
 * Only a file inside the data folder is backed up, so a scratch copy or a test file never creates a backup in the real data folder.
 * Python twin: python/job_scoring/auto_backup.py (same layout, names and retention).
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE } from './atomic-file.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const DATA_ROOT = path.join(ROOT, 'data')
export const AUTO_BACKUP_FILES = ['candidate-intelligence.json', 'candidate-profile.json', 'profile-enrichment.json', 'scored_jobs.json']
export const KEEP_DEFAULT = 10
export const KEEP_BY_FILE = { 'scored_jobs.json': 3 }
const VERSION_NAME = /^\d{8}-\d{6}(-\d+)?\.json$/

export class BackupError extends Error {
  constructor(file) {
    super(`The backup before writing ${file} could not be made, so nothing was changed.`)
    this.name = 'BackupError'
    this.code = 'backup_failed'
    this.status = 500
  }
}

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex')
const stamp = (d) => d.toISOString().replace(/\.\d+Z$/, '').replace(/[-:]/g, '').replace('T', '-')

/** What "the same content" means: the profile without its save stamp, everything else byte for byte. */
function comparable(name, buf) {
  if (name !== 'candidate-profile.json') return buf
  try {
    const doc = JSON.parse(buf.toString('utf8'))
    if (doc && doc.meta) delete doc.meta.updatedAt
    return Buffer.from(JSON.stringify(doc))
  } catch {
    return buf
  }
}

function insideDir(file, dir) {
  const rel = path.relative(path.resolve(dir), path.resolve(file))
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel)
}

/** Keep the newest `keep` versions in `dir`. A failure to remove an old one never blocks the write that follows. */
function prune(dir, keep) {
  try {
    const names = fs.readdirSync(dir).filter((n) => VERSION_NAME.test(n)).sort()
    for (const old of names.slice(0, Math.max(0, names.length - keep))) {
      try { fs.unlinkSync(path.join(dir, old)) } catch (e) { console.warn(`[auto-backup] could not remove an old version of ${path.basename(dir)}: ${e.code || 'error'}`) }
    }
  } catch (e) {
    console.warn(`[auto-backup] could not list the versions of ${path.basename(dir)}: ${e.code || 'error'}`)
  }
}

/**
 * Back up `file` as it is now, if `newData` would change it. Returns { path, sha256 } of the backup, or null when none was needed
 * (not a guarded file, outside the data folder, no file yet, or identical content). Throws BackupError when it cannot be made.
 */
export function backupBeforeWrite(file, newData, { dataRoot = DATA_ROOT, now = new Date() } = {}) {
  const name = path.basename(file)
  if (!AUTO_BACKUP_FILES.includes(name) || !insideDir(file, dataRoot)) return null
  let current
  try {
    current = fs.readFileSync(file)
  } catch (e) {
    if (e.code === 'ENOENT') return null
    console.error(`[auto-backup] ${name}: the current file cannot be read: ${e.code || 'error'}`)
    throw new BackupError(name)
  }
  const incoming = Buffer.isBuffer(newData) ? newData : Buffer.from(String(newData), 'utf8')
  if (Buffer.compare(comparable(name, current), comparable(name, incoming)) === 0) return null
  const dir = path.join(dataRoot, 'backups', 'auto', name)
  let target
  try {
    fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
    const base = stamp(now)
    target = path.join(dir, `${base}.json`)
    for (let n = 2; fs.existsSync(target); n += 1) target = path.join(dir, `${base}-${n}.json`)
    const fd = fs.openSync(target, 'wx', PRIVATE_FILE_MODE)
    try {
      fs.fchmodSync(fd, PRIVATE_FILE_MODE)
      fs.writeFileSync(fd, current)
      fs.fsyncSync(fd)
    } finally {
      fs.closeSync(fd)
    }
    if (sha256(fs.readFileSync(target)) !== sha256(current)) throw new Error('the copy does not match')
  } catch (e) {
    console.error(`[auto-backup] ${name}: backup failed: ${e.code || e.message}`)
    if (target) { try { fs.unlinkSync(target) } catch { /* nothing to remove */ } }
    throw new BackupError(name)
  }
  prune(dir, KEEP_BY_FILE[name] ?? KEEP_DEFAULT)
  return { path: target, sha256: sha256(current) }
}
