// Vitest global setup: the second guard, for what the in-process fs guard (realDataGuard.js) cannot see. A test that spawns a process
// (a Python runner, `node`, `rm`) writes with that process's own fs. The owner-private paths are listed by size and modification time
// before the run (stat only: no file is opened or read) and again after it; any difference fails the run and names the paths.
// The same paths as tests/python/real_data_guard.py (tests/js/realDataGuard.test.js checks the two lists agree).
// Pipeline-written files are not listed: the owner's own scrape may change them while the tests run.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const GUARDED_DIRS = ['data/profile', 'data/intelligence', 'data/applications']
export const GUARDED_FILES = ['data/jobs/manual_jobs.json', 'data/jobs/job-state.json']
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

/** { relative path: "size:mtimeNs" } of every guarded file. */
export function fingerprint(root = ROOT) {
  const found = {}
  const add = (file) => {
    try {
      const stat = fs.statSync(file, { bigint: true })
      found[path.relative(root, file)] = `${stat.size}:${stat.mtimeNs}`
    } catch { /* absent */ }
  }
  const walk = (dir) => {
    let entries
    try { entries = fs.readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else add(full)
    }
  }
  for (const dir of GUARDED_DIRS) walk(path.join(root, dir))
  for (const file of GUARDED_FILES) add(path.join(root, file))
  return found
}

/** Paths added, removed or changed between two fingerprints (names only). */
export function changes(before, after) {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter((p) => before[p] !== after[p])
    .map((p) => `${!(p in before) ? 'added' : !(p in after) ? 'removed' : 'changed'}: ${p}`)
    .sort()
}

export default function setup() {
  const before = fingerprint()
  return () => {
    const moved = changes(before, fingerprint())
    if (moved.length) {
      throw new Error(`REAL DATA CHANGED DURING THE TEST RUN (a test must use a temp directory; if you saved the profile in the app meanwhile, run again):\n  ${moved.join('\n  ')}`)
    }
  }
}
