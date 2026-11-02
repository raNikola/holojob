/**
 * Replace a file whole, so a crash leaves the old file or the new one, never half of one.
 * Node counterpart of python/job_scoring/atomic_write.py.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Temp file next to the target, fsync, rename. On failure the target is untouched and the temp file is gone.
 *
 * An existing target keeps its permission bits, and the temp file has them before any byte is written, so a
 * 600 file's content is never readable by others. A new file gets the process default (umask). A symlink is
 * written through, not replaced. The parent directory must exist. The temp name does not include the file's
 * name, so a name near the file system's length limit still works.
 */
export function replaceFileAtomic(file, data) {
  let target = file
  let mode
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
