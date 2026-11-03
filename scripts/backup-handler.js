/**
 * Holojob full-state backup export/import.
 */

import fs from 'node:fs'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import { createRequire } from 'node:module'
import { isStoreBackupEntry, mergeFromBackup } from './application-store.js'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'
import { isSecretPath, safeRelativePath } from './secret-paths.js'

const require = createRequire(import.meta.url)
const { ZipArchive } = require('archiver')
const AdmZip = require('adm-zip')

// Restored files new to these folders are private; an existing file keeps its mode. Application entries go through
// the store's own private writes. Same list: scripts/tighten-data-permissions.sh.
const PRIVATE_RESTORE = /^data\/(profile|profile\.bak-[^/]+|ai|config|backups|intelligence|outreach|interviews|analytics|resumes)\//

// The lock must stay the same file: flock holds an inode, and renaming a copy over it would free it for the next process.
const RUN_LOCK = 'data/jobs/.pipeline.lock'

const DATA_DIRS = ['profile', 'intelligence', 'jobs', 'resumes', 'outreach', 'audits', 'cache', 'applications']

export function createBackupStream(root, clientPayload = {}) {
  const archive = new ZipArchive({ zlib: { level: 9 } })
  const stream = new PassThrough()
  archive.pipe(stream)

  for (const dir of DATA_DIRS) {
    const abs = path.join(root, 'data', dir)
    if (fs.existsSync(abs)) {
      // Credentials are left out here, in the one place that lists them (secret-paths.js).
      archive.directory(abs, `data/${dir}`, (entry) => (isSecretPath(`data/${dir}/${entry.name}`) ? false : entry))
    }
  }

  if (clientPayload.profile) {
    archive.append(JSON.stringify(clientPayload.profile, null, 2), {
      name: 'data/profile/candidate-profile.json',
    })
  }
  if (clientPayload.intelligence) {
    archive.append(JSON.stringify(clientPayload.intelligence, null, 2), {
      name: 'data/intelligence/candidate-intelligence.json',
    })
  }
  if (clientPayload.jobs) {
    archive.append(JSON.stringify(clientPayload.jobs, null, 2), {
      name: 'data/jobs/scored_jobs.json',
    })
  }

  archive.append(JSON.stringify({
    exportedAt: new Date().toISOString(),
    version: '1.0',
    app: 'holojob',
  }, null, 2), { name: 'backup-manifest.json' })

  archive.finalize()
  return stream
}

/**
 * Restore a backup zip. Every data/ entry is written over the file on disk, except the
 * application store: its entries are merged, so a restore adds history and never
 * removes or rewrites it.
 *
 * An archive with an absolute path or a ".." anywhere is refused whole, before anything is written.
 * Entries naming a credential (secret-paths.js) are skipped and listed in `refused`.
 */
export async function importBackupZip(root, zipBuffer, options = {}) {
  const zip = new AdmZip(zipBuffer)
  const entries = zip.getEntries()
  const restored = []
  const refused = []
  const storeEntries = []
  const dataRoot = path.resolve(root, 'data') + path.sep

  for (const entry of entries) {
    if (safeRelativePath(entry.entryName) === null) {
      throw new Error(`Backup refused: unsafe path in the archive (${JSON.stringify(entry.entryName).slice(0, 80)})`)
    }
  }

  for (const entry of entries) {
    if (entry.isDirectory) continue
    const name = safeRelativePath(entry.entryName)
    if (!name.startsWith('data/')) continue
    if (isSecretPath(name)) {
      refused.push(name)
      continue
    }
    if (name === RUN_LOCK) continue
    if (isStoreBackupEntry(name)) {
      storeEntries.push({ name, data: entry.getData() })
      continue
    }
    const dest = path.resolve(root, name)
    if (!dest.startsWith(dataRoot)) {
      throw new Error(`Backup refused: path leaves data/ (${name.slice(0, 80)})`)
    }
    if (PRIVATE_RESTORE.test(name)) {
      fs.mkdirSync(path.dirname(dest), { recursive: true, mode: PRIVATE_DIR_MODE })
      replaceFileAtomic(dest, entry.getData(), { mode: PRIVATE_FILE_MODE })
    } else {
      fs.mkdirSync(path.dirname(dest), { recursive: true })
      replaceFileAtomic(dest, entry.getData())
    }
    restored.push(name)
  }

  const applications = storeEntries.length ? await mergeFromBackup(root, storeEntries, options) : null
  return { ok: true, restored, count: restored.length, refused, applications }
}
