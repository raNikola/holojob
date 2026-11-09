/**
 * Backup of the profile taken when an import is applied (and only then: never on an ordinary profile save).
 *
 * The browser is the master of the profile until Step 5, so the body of the request is the browser's current profile, not the
 * server's mirror (which may be older). It is written to data/backups/profile-import-<YYYYMMDD-HHMMSS>[-n]/candidate-profile.json
 * (600, folders 700), read back and parsed before the call answers. Profile JSON only: no stored CV files. Only the newest
 * `keep` folders of this kind are kept; nothing else under data/backups is ever touched.
 *
 * Fixed answers only: nothing from the profile or from an exception is echoed or logged.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'

export const IMPORT_BACKUP_KEEP = 10
export const BACKUP_FILE = 'candidate-profile.json'
const FOLDER = /^profile-import-\d{8}-\d{6}(-\d+)?$/

export const BACKUP_ERRORS = {
  invalid_profile: { status: 400, error: 'The profile to back up was not valid.' },
  backup_failed: { status: 500, error: 'The backup could not be made, so nothing was changed.' },
}

export class BackupError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}

const stamp = (d) => {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/** Folders of this kind, oldest first (the stamp sorts as text; a "-n" suffix sorts after its base). */
export function listImportBackups(backupsDir) {
  const key = (name) => {
    const [, at, n] = /^profile-import-(\d{8}-\d{6})(?:-(\d+))?$/.exec(name)
    return [at, Number(n ?? 1)]
  }
  try {
    return fs.readdirSync(backupsDir).filter((n) => FOLDER.test(n)).sort((a, b) => {
      const [ta, na] = key(a)
      const [tb, nb] = key(b)
      return ta === tb ? na - nb : ta < tb ? -1 : 1
    })
  } catch {
    return []
  }
}

/**
 * @param {string} root
 * @param {object} profile the browser's current profile
 * @returns {{ path: string, sha256: string, bytes: number, kept: number, pruned: number }}
 */
export function backupProfileForImport(root, profile, { now = () => new Date(), keep = IMPORT_BACKUP_KEEP } = {}) {
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) throw new BackupError('invalid_profile')
  const backups = path.join(root, 'data/backups')
  try {
    const text = `${JSON.stringify(profile, null, 2)}\n`
    fs.mkdirSync(backups, { recursive: true, mode: PRIVATE_DIR_MODE })
    const base = `profile-import-${stamp(now())}`
    let name = base
    for (let i = 2; fs.existsSync(path.join(backups, name)); i += 1) name = `${base}-${i}`
    const dir = path.join(backups, name)
    fs.mkdirSync(dir, { mode: PRIVATE_DIR_MODE })
    const file = path.join(dir, BACKUP_FILE)
    replaceFileAtomic(file, text, { mode: PRIVATE_FILE_MODE })
    const back = fs.readFileSync(file)
    JSON.parse(back.toString('utf-8')) // a backup that cannot be read back is no backup
    const sha256 = crypto.createHash('sha256').update(back).digest('hex')
    const all = listImportBackups(backups)
    const drop = all.slice(0, Math.max(0, all.length - keep)).filter((n) => n !== name)
    for (const old of drop) fs.rmSync(path.join(backups, old), { recursive: true, force: true })
    return { path: path.relative(root, file), sha256, bytes: back.length, kept: all.length - drop.length, pruned: drop.length }
  } catch (e) {
    if (e instanceof BackupError) throw e
    throw new BackupError('backup_failed')
  }
}
