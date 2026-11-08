#!/usr/bin/env node
/**
 * Writes the job ids that have an application, one per line, to a file: the list Python needs and may not read for itself
 * (TRACKER_PLAN 6a). Read-only on the store. Only ids are written: no title, company, note or contact.
 *
 *   podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \
 *     node scripts/export-application-job-ids.js data/backups/application-job-ids.txt
 *
 * The output file is private (mode 600) and lives under data/, which git ignores. Feed it to scripts/older-key-report.py and
 * scripts/prune-older-key.py with --application-job-ids.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadStore } from './application-store.js'

/** The distinct job ids of the applications in `store`, sorted. Applications entered by hand have none. */
export function applicationJobIds(store) {
  const ids = new Set()
  for (const app of Object.values(store?.applications ?? {})) {
    const id = app?.posting?.jobId
    if (typeof id === 'string' && /^[^\s#]{1,200}$/.test(id)) ids.add(id)
  }
  return [...ids].sort()
}

export function exportApplicationJobIds(root, outFile) {
  const ids = applicationJobIds(loadStore(root))
  fs.mkdirSync(path.dirname(outFile), { recursive: true, mode: 0o700 })
  fs.writeFileSync(outFile, ids.length ? `${ids.join('\n')}\n` : '', { mode: 0o600 })
  fs.chmodSync(outFile, 0o600)
  return ids.length
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = process.argv[2]
  if (!out) {
    console.error('usage: node scripts/export-application-job-ids.js OUT_FILE')
    process.exit(2)
  }
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  console.log(`wrote ${exportApplicationJobIds(root, path.resolve(out))} job ids to ${out}`)
}
