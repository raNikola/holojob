// No test may change anything under the real data/ folder (the owner's profile, intelligence, applications, jobs, secrets).
//
// Incident, 2026-11-09: two tests mocked fs.writeFileSync and fs.mkdirSync to "intercept" a write, then the profile writer became
// temp file + rename; the rename was not mocked, so an empty temp file replaced the real data/profile/candidate-profile.json.
// Mocking one fs call is not a guard. This file is: every fs call that creates, changes, moves or removes a path is refused when that
// path is under the repo's data/ folder, whatever else a test has mocked. A test that needs a store points it at a temp dir.
//
// tests/js/realDataGuard.test.js keeps this honest. The guard reports the path relative to the repo, never any content.

import fs from 'node:fs'
import { syncBuiltinESMExports } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REAL_DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../data')
const FLAG_WRITES = /[wa+]/

function asPath(value) {
  if (value instanceof URL) return fileURLToPath(value)
  return typeof value === 'string' ? value : Buffer.isBuffer(value) ? value.toString() : null
}

export function isRealData(value) {
  const raw = asPath(value)
  if (!raw) return false // a file descriptor or nothing: it was opened by a call that was checked
  const abs = path.resolve(raw)
  return abs === REAL_DATA || abs.startsWith(REAL_DATA + path.sep)
}

function refuse(name, value) {
  const shown = path.relative(path.resolve(REAL_DATA, '..'), path.resolve(asPath(value)))
  throw new Error(`Refused: a test called fs.${name} on ${shown}, which is under the real data/ folder. Point the code at a temp directory.`)
}

// [function, which argument positions are paths that would be changed]
const PATH_WRITERS = {
  writeFileSync: [0], appendFileSync: [0], writeFile: [0], appendFile: [0],
  mkdirSync: [0], mkdir: [0], mkdtempSync: [0],
  rmSync: [0], rm: [0], rmdirSync: [0], rmdir: [0], unlinkSync: [0], unlink: [0],
  renameSync: [0, 1], rename: [0, 1],
  copyFileSync: [1], copyFile: [1], cpSync: [1], cp: [1],
  truncateSync: [0], truncate: [0],
  symlinkSync: [1], symlink: [1], linkSync: [1], link: [1],
  chmodSync: [0], chmod: [0], chownSync: [0], chown: [0], utimesSync: [0], utimes: [0],
  createWriteStream: [0],
}

// The promise forms reject instead of throwing, as the real ones do.
function wrap(target, name, positions, promises = false) {
  const original = target[name]
  if (typeof original !== 'function') return
  const check = (args) => {
    for (const position of positions) if (isRealData(args[position])) refuse(name, args[position])
  }
  target[name] = promises
    ? async function guardedPromise(...args) { check(args); return original.apply(this, args) }
    : function guarded(...args) { check(args); return original.apply(this, args) }
}

for (const [name, positions] of Object.entries(PATH_WRITERS)) {
  wrap(fs, name, positions)
  wrap(fs.promises, name, positions, true)
}

// Opening for writing is the other way in: openSync(path, 'w' | 'wx' | 'a' | 'r+').
for (const target of [fs, fs.promises]) {
  for (const name of ['openSync', 'open']) {
    const original = target[name]
    if (typeof original !== 'function') continue
    const check = (file, flags) => {
      const writing = typeof flags === 'number' ? (flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_APPEND)) !== 0 : FLAG_WRITES.test(String(flags))
      if (writing && isRealData(file)) refuse(name, file)
    }
    target[name] = target === fs.promises
      ? async function guardedOpenPromise(file, flags = 'r', ...rest) { check(file, flags); return original.call(this, file, flags, ...rest) }
      : function guardedOpen(file, flags = 'r', ...rest) { check(file, flags); return original.call(this, file, flags, ...rest) }
  }
}

// `import { writeFileSync } from 'node:fs'` (and 'node:fs/promises') bind to the original functions until the builtin's ESM exports are
// re-synced from the patched objects above; without this a module that uses named imports would bypass the guard.
syncBuiltinESMExports()
