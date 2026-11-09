#!/usr/bin/env node
/**
 * Writes the job ids the server knows the owner has acted on (Keep, Saved, Rejected in data/jobs/job-state.json), one per line, for
 * `prune-older-key.py --protect-ids`. Read-only on the state file. Ids only. Mode 600.
 *
 *   podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \
 *     node scripts/export-protect-ids.js data/backups/protect-ids.txt
 *
 * Ids that exist only in the browser are NOT here until the owner imports the browser state (Settings, preview then confirm).
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadState } from './job-state-store.js'

/** The distinct job ids of entries that are kept or have a status other than `new`, sorted. */
export function protectedJobIds(doc) {
  const ids = new Set()
  for (const entry of Object.values(doc?.jobs ?? {})) {
    if ((entry.keep === true || entry.status !== 'new') && typeof entry.jobId === 'string' && /^[^\s#]{1,200}$/.test(entry.jobId)) ids.add(entry.jobId)
  }
  return [...ids].sort()
}

export function exportProtectIds(root, outFile) {
  const ids = protectedJobIds(loadState(root).doc)
  fs.mkdirSync(path.dirname(outFile), { recursive: true, mode: 0o700 })
  fs.writeFileSync(outFile, ids.length ? `${ids.join('\n')}\n` : '', { mode: 0o600 })
  fs.chmodSync(outFile, 0o600)
  return ids.length
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = process.argv[2]
  if (!out) {
    console.error('usage: node scripts/export-protect-ids.js OUT_FILE')
    process.exit(2)
  }
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  console.log(`wrote ${exportProtectIds(root, path.resolve(out))} job ids to ${out}`)
}
