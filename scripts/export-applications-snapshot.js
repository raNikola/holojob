#!/usr/bin/env node
/**
 * Read-only copy of the application store for the owner to keep before any Wave 6 apply step:
 * the store folder {applications.json, settings.json, files/**} -> data/backups/applications-<ts>/ with a
 * manifest.json (sha256 and size per file). Nothing in the store folder is written. New folders are 700, files 600.
 *
 *   podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \
 *     node scripts/export-applications-snapshot.js
 *
 * Prints counts and the store sha256 only, never a value from a record.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { storePaths } from './application-store.js'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, copyToNewFile, replaceFileAtomic } from './atomic-file.js'

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex')

function listFiles(dir, base = dir) {
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return listFiles(full, base)
    return entry.isFile() ? [path.relative(base, full)] : []
  }).sort()
}

function stamp(date) {
  return date.toISOString().replace(/[-:]/g, '').replace(/\..*/, '').replace('T', '-')
}

/** @returns {{ dir: string, fileCount: number, storeSha256: string|null }} */
export function exportApplicationsSnapshot(root, { now = () => new Date() } = {}) {
  const source = storePaths(root).dir // the store module owns the path (the isolation test confines it to one module)
  const files = listFiles(source)
  const dir = path.join(root, 'data/backups', `applications-${stamp(now())}`)
  fs.mkdirSync(path.join(root, 'data/backups'), { recursive: true, mode: PRIVATE_DIR_MODE })
  fs.mkdirSync(dir, { mode: PRIVATE_DIR_MODE }) // an existing folder throws: a snapshot is never overwritten
  const manifest = { version: 1, createdAt: now().toISOString(), files: {} }
  for (const rel of files) {
    const dest = path.join(dir, rel)
    fs.mkdirSync(path.dirname(dest), { recursive: true, mode: PRIVATE_DIR_MODE })
    copyToNewFile(path.join(source, rel), dest, PRIVATE_FILE_MODE)
    const bytes = fs.readFileSync(dest)
    manifest.files[rel] = { sha256: sha256(bytes), bytes: bytes.length }
  }
  replaceFileAtomic(path.join(dir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, { mode: PRIVATE_FILE_MODE })
  return { dir, fileCount: files.length, storeSha256: manifest.files['applications.json']?.sha256 ?? null }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const result = exportApplicationsSnapshot(root)
  console.log(`wrote ${result.fileCount} files to ${path.relative(root, result.dir)}; applications.json sha256 ${result.storeSha256 ?? '(none)'}`)
}
