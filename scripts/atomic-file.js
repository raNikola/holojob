/**
 * Replace a file whole, so a crash leaves the old file or the new one, never half of one.
 * Node counterpart of python/job_scoring/atomic_write.py.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

/** Modes of new files and directories in the private data folders (no login, so nothing there is world-readable). */
export const PRIVATE_FILE_MODE = 0o600
export const PRIVATE_DIR_MODE = 0o700

/**
 * Temp file next to the target, fsync, rename. On failure the target is untouched and the temp file is gone.
 *
 * An existing target keeps its permission bits, and the temp file has them before any byte is written, so a
 * 600 file's content is never readable by others. A new file gets options.mode, else the process default
 * (umask); options.mode never changes an existing target. A symlink is written through, not replaced. The parent directory must exist. The temp name does not include the file's
 * name, so a name near the file system's length limit still works.
 */
export function replaceFileAtomic(file, data, { mode: newFileMode } = {}) {
  let target = file
  let mode = newFileMode
  try {
    target = fs.realpathSync(file)
    mode = fs.statSync(target).mode & 0o777
  } catch (e) {
    if (e.code !== 'ENOENT') throw e
  }
  const dir = path.dirname(target)
  const tmp = path.join(dir, `.atomic-${crypto.randomUUID()}.tmp`)
  let fd
  try {
    fd = fs.openSync(tmp, 'wx', mode ?? 0o666)
    if (mode !== undefined) fs.fchmodSync(fd, mode) // the open above is narrowed by the umask
    fs.writeFileSync(fd, data)
    fs.fsyncSync(fd)
    fs.closeSync(fd)
    fd = undefined
    fs.renameSync(tmp, target)
  } catch (e) {
    if (fd !== undefined) {
      try { fs.closeSync(fd) } catch { /* already failing */ }
    }
    fs.rmSync(tmp, { force: true })
    throw e
  }
  try {
    const dirFd = fs.openSync(dir, 'r')
    try { fs.fsyncSync(dirFd) } finally { fs.closeSync(dirFd) }
  } catch {
    // directory fsync is best effort (not supported everywhere)
  }
}

/**
 * Copy src to a new file with exactly `mode`, whatever src's mode is (fs.copyFileSync would carry src's over).
 * An existing dest throws EEXIST and is left alone; a failed write leaves no dest.
 */
export function copyToNewFile(src, dest, mode) {
  const data = fs.readFileSync(src)
  let fd = fs.openSync(dest, 'wx', mode)
  try {
    fs.fchmodSync(fd, mode) // the open above is narrowed by the umask
    fs.writeFileSync(fd, data)
    fs.closeSync(fd)
    fd = undefined
  } catch (e) {
    if (fd !== undefined) {
      try { fs.closeSync(fd) } catch { /* already failing */ }
    }
    fs.rmSync(dest, { force: true })
    throw e
  }
}
