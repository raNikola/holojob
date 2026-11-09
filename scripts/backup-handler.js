/**
 * Holojob full-state backup export/import.
 */

import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createHash } from 'node:crypto'
import { PassThrough } from 'node:stream'
import { createRequire } from 'node:module'
import { isStoreBackupEntry, mergeFromBackup } from './application-store.js'
import { isJobStateBackupEntry, mergeStateFromBackup } from './job-state-store.js'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'
import { isSecretPath, safeRelativePath } from './secret-paths.js'

const require = createRequire(import.meta.url)
const { ZipArchive } = require('archiver')
const AdmZip = require('adm-zip')

// Restored files new to these folders are private; an existing file keeps its mode. Application entries go through
// the store's own private writes. Same list: scripts/tighten-data-permissions.sh.
const PRIVATE_RESTORE = /^data\/(profile|profile\.bak-[^/]+|ai|config|backups|intelligence|outreach|interviews|analytics|resumes)\//

// Never restored. The lock must stay the same file: flock holds an inode, and renaming a copy over it would free it for the
// next process. A commit marker from an archive would report an incomplete save that did not happen here.
const RUN_STATE_FILES = new Set(['data/jobs/.pipeline.lock', 'data/jobs/.view.lock', 'data/analytics/runs/.commit-in-progress.json'])

// What a scrape has collected so far, and the ledger as the run found it (hard link): working state of one run, private,
// pruned to the last three runs. Neither exported nor restored: a restored folder would look like an unimported run.
const STAGING_DIR = 'data/jobs/staging'
const isStagingPath = (name) => name === STAGING_DIR || name.startsWith(`${STAGING_DIR}/`)

// data/analytics (run records and event logs, kept 90 days) is in: nothing else holds them, so a lost folder is not rebuilt.
// Not in, on purpose: data/ai (budget ledger, settings), data/config, data/secrets (see docs/DECISIONS.md, Wave 0).
const DATA_DIRS = ['profile', 'intelligence', 'jobs', 'resumes', 'outreach', 'audits', 'cache', 'applications', 'analytics']
const MANIFEST_NAME = 'backup-manifest.json'
const MANIFEST_VERSION = '2.0'

const sha256Of = (data) => createHash('sha256').update(data).digest('hex')

function isLeftOut(name) {
  return isSecretPath(name) || isStagingPath(name) || name === 'data/jobs/.view.lock' || RUN_STATE_FILES.has(name)
}

/** { 'data/jobs/x.json': absolutePath } for every regular file the backup covers (symlinks are not followed). */
function collectFiles(root) {
  const found = new Map()
  const walk = (abs, name) => {
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
      const childName = `${name}/${entry.name}`
      if (isLeftOut(childName)) continue
      if (entry.isDirectory()) walk(path.join(abs, entry.name), childName)
      else if (entry.isFile()) found.set(childName, path.join(abs, entry.name))
    }
  }
  for (const dir of DATA_DIRS) {
    const abs = path.join(root, 'data', dir)
    if (fs.existsSync(abs) && fs.statSync(abs).isDirectory()) walk(abs, `data/${dir}`)
  }
  return found
}

/**
 * The archive: every file once, then backup-manifest.json with each file's sha256 and size. A file is read once, so the
 * hash is of the bytes in the zip. The browser's profile, intelligence and job list (Keep, statuses live only there)
 * replace the server's copy of the same name; the manifest says which of the three were sent.
 */
export function createBackupStream(root, clientPayload = {}) {
  const archive = new ZipArchive({ zlib: { level: 9 } })
  const stream = new PassThrough()
  archive.pipe(stream)

  const contents = new Map()
  for (const [name, abs] of collectFiles(root)) contents.set(name, fs.readFileSync(abs))
  const fromBrowser = {
    profile: ['data/profile/candidate-profile.json', clientPayload.profile],
    intelligence: ['data/intelligence/candidate-intelligence.json', clientPayload.intelligence],
    jobs: ['data/jobs/scored_jobs.json', clientPayload.jobs],
  }
  const browserState = {}
  for (const [key, [name, value]] of Object.entries(fromBrowser)) {
    browserState[key] = Boolean(value)
    if (value) contents.set(name, Buffer.from(JSON.stringify(value, null, 2)))
  }

  const files = {}
  for (const [name, data] of contents) {
    archive.append(data, { name })
    files[name] = { sha256: sha256Of(data), bytes: data.length }
  }
  archive.append(JSON.stringify({
    exportedAt: new Date().toISOString(),
    version: MANIFEST_VERSION,
    app: 'holojob',
    browserState,
    files,
  }, null, 2), { name: MANIFEST_NAME })

  archive.finalize()
  return stream
}

/**
 * Check an archive against its manifest without writing anything. { ok, hashed, files, problems }.
 * `hashed` is false for an archive older than the manifest hashes (nothing to check against: ok stays true, the
 * caller decides). Problems: a file whose bytes differ, a file the manifest lists but the zip lacks, a file in the zip the
 * manifest does not list (anything added after the export), an unreadable manifest.
 */
export function verifyBackupZip(zipBuffer) {
  const zip = new AdmZip(zipBuffer)
  const problems = []
  const entries = new Map()
  for (const entry of zip.getEntries()) {
    if (entry.isDirectory) continue
    const name = safeRelativePath(entry.entryName) ?? entry.entryName
    if (entries.has(name)) problems.push({ name, reason: 'listed twice in the archive' })
    entries.set(name, entry)
  }
  const manifestEntry = entries.get(MANIFEST_NAME)
  if (!manifestEntry) return { ok: problems.length === 0, hashed: false, files: 0, problems, manifest: null } // an archive from before manifests
  let manifest = null
  try {
    manifest = JSON.parse(manifestEntry.getData().toString('utf-8'))
  } catch {
    // handled below
  }
  if (!manifest || typeof manifest !== 'object') {
    return { ok: false, hashed: false, files: 0, problems: [{ name: MANIFEST_NAME, reason: 'missing or unreadable' }], manifest: null }
  }
  if (!manifest.files || typeof manifest.files !== 'object') {
    return { ok: problems.length === 0, hashed: false, files: 0, problems, manifest }
  }
  for (const [name, meta] of Object.entries(manifest.files)) {
    const entry = entries.get(name)
    if (!entry) problems.push({ name, reason: 'missing from the archive' })
    else if (sha256Of(entry.getData()) !== meta?.sha256) problems.push({ name, reason: 'hash differs' })
  }
  for (const name of entries.keys()) {
    if (name !== MANIFEST_NAME && !(name in manifest.files)) problems.push({ name, reason: 'not in the manifest' })
  }
  return { ok: problems.length === 0, hashed: true, files: Object.keys(manifest.files).length, problems, manifest }
}

/**
 * The restore check: verify the archive, restore it into a throwaway directory (never `root`'s data), then compare the
 * sha256 of each restored file with the manifest. Application entries are merged by the store (not copied), so they are
 * compared in the archive only and counted in `merged`. Returns { ok, hashed, checked, merged, refused, problems }.
 */
export async function checkBackupRestore(zipBuffer, { tmpBase = os.tmpdir() } = {}) {
  const verified = verifyBackupZip(zipBuffer)
  const report = { ok: verified.ok, hashed: verified.hashed, checked: 0, merged: 0, refused: [], problems: [...verified.problems] }
  if (!verified.ok || !verified.hashed) return report
  const temp = fs.mkdtempSync(path.join(tmpBase, 'backup-check-'))
  try {
    const result = await importBackupZip(temp, zipBuffer)
    report.refused = result.refused
    for (const [name, meta] of Object.entries(verified.manifest.files)) {
      if (RUN_STATE_FILES.has(name)) continue
      if (isStoreBackupEntry(name)) {
        report.merged += 1
        continue
      }
      const dest = path.join(temp, name)
      if (!fs.existsSync(dest)) report.problems.push({ name, reason: 'not restored' })
      else if (sha256Of(fs.readFileSync(dest)) !== meta.sha256) report.problems.push({ name, reason: 'restored bytes differ' })
      else report.checked += 1
    }
  } catch (e) {
    report.problems.push({ name: '(restore)', reason: String(e.message).slice(0, 120) })
  } finally {
    fs.rmSync(temp, { recursive: true, force: true })
  }
  report.ok = report.problems.length === 0
  return report
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
  let jobState = null
  const storeEntries = []
  const dataRoot = path.resolve(root, 'data') + path.sep

  for (const entry of entries) {
    if (safeRelativePath(entry.entryName) === null) {
      throw new Error(`Backup refused: unsafe path in the archive (${JSON.stringify(entry.entryName).slice(0, 80)})`)
    }
  }

  // A manifest with hashes must match the archive before the first byte is written. An older archive has none:
  // it is restored as before and the answer says `verified: false`.
  const verification = verifyBackupZip(zipBuffer)
  if (!verification.ok) {
    const first = verification.problems.slice(0, 3).map((p) => `${p.name} (${p.reason})`).join(', ')
    throw new Error(`Backup refused: it does not match its manifest, nothing was restored: ${first}`)
  }

  for (const entry of entries) {
    if (entry.isDirectory) continue
    const name = safeRelativePath(entry.entryName)
    if (!name.startsWith('data/')) continue
    if (isSecretPath(name)) {
      refused.push(name)
      continue
    }
    if (RUN_STATE_FILES.has(name) || isStagingPath(name)) continue
    if (isStoreBackupEntry(name)) {
      storeEntries.push({ name, data: entry.getData() })
      continue
    }
    if (isJobStateBackupEntry(name)) {
      // Never replaced: entries are added where missing, the live ones stay (job-state-store.js).
      const merged = mergeStateFromBackup(root, entry.getData())
      if (merged.refused) refused.push(`${name} (${merged.refused})`)
      else jobState = merged
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
  return { ok: true, restored, count: restored.length, refused, applications, jobState, verified: verification.hashed }
}
