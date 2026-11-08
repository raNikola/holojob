import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { importBackupZip } from '../../scripts/backup-handler.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')

const REL = 'data/jobs/scored_jobs.json'
const OLD = '{"jobs":["old"]}'
const NEW = '{"jobs":["new"]}'

let root

const abs = (rel) => path.join(root, rel)
const modeOf = (rel) => fs.statSync(abs(rel)).mode & 0o777
const tempFiles = (rel) => fs.readdirSync(path.dirname(abs(rel))).filter((f) => f.endsWith('.tmp'))

function write(rel, content, mode) {
  fs.mkdirSync(path.dirname(abs(rel)), { recursive: true })
  fs.writeFileSync(abs(rel), content)
  if (mode !== undefined) fs.chmodSync(abs(rel), mode)
}

function zipOf(entries) {
  const zip = new AdmZip()
  for (const [name, data] of Object.entries(entries)) zip.addFile(name, Buffer.from(data))
  return zip.toBuffer()
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'restore-atomic-'))
})

afterEach(() => {
  vi.restoreAllMocks()
  fs.rmSync(root, { recursive: true, force: true })
})

describe('backup restore: a failure leaves the old file', () => {
  beforeEach(() => write(REL, OLD))

  async function expectOldFileKept(message) {
    await expect(importBackupZip(root, zipOf({ [REL]: NEW }))).rejects.toThrow(message)
    expect(fs.readFileSync(abs(REL), 'utf-8')).toBe(OLD)
    expect(tempFiles(REL)).toEqual([])
  }

  it('when the write dies half way', async () => {
    const realWrite = fs.writeFileSync
    vi.spyOn(fs, 'writeFileSync').mockImplementationOnce((fd, data) => {
      realWrite(fd, data.subarray(0, 5))
      throw new Error('EIO')
    })
    await expectOldFileKept('EIO')
  })

  it('when the fsync fails', async () => {
    vi.spyOn(fs, 'fsyncSync').mockImplementationOnce(() => { throw new Error('EIO') })
    await expectOldFileKept('EIO')
  })

  it('when the rename fails', async () => {
    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    await expectOldFileKept('disk full')
  })
})

describe('backup restore: modes', () => {
  it('keeps an existing 600 file at 600, and restores its content', async () => {
    const rel = 'data/ai/findings/job/a.json'
    write(rel, OLD, 0o600)
    await importBackupZip(root, zipOf({ [rel]: NEW }))
    expect(modeOf(rel)).toBe(0o600)
    expect(fs.readFileSync(abs(rel), 'utf-8')).toBe(NEW)
  })

  it('keeps the temp file at 600 while the content is being written', async () => {
    const rel = 'data/ai/findings/job/a.json'
    write(rel, OLD, 0o600)
    const realWrite = fs.writeFileSync
    let modeDuringWrite
    vi.spyOn(fs, 'writeFileSync').mockImplementationOnce((fd, data) => {
      modeDuringWrite = fs.fstatSync(fd).mode & 0o777
      realWrite(fd, data)
    })
    await importBackupZip(root, zipOf({ [rel]: NEW }))
    expect(modeDuringWrite).toBe(0o600)
  })

  it('keeps a mode wider than the umask', async () => {
    write(REL, OLD, 0o666)
    await importBackupZip(root, zipOf({ [REL]: NEW }))
    expect(modeOf(REL)).toBe(0o666)
  })

  it('gives a new file the default mode, as a plain write does', async () => {
    write('data/jobs/plain.json', OLD)
    await importBackupZip(root, zipOf({ 'data/jobs/new.json': NEW }))
    expect(modeOf('data/jobs/new.json')).toBe(modeOf('data/jobs/plain.json'))
  })
})

describe('backup restore: same result as a plain write', () => {
  it('writes identical bytes and reports the same shape', async () => {
    const entries = {
      'data/jobs/empty.json': Buffer.alloc(0),
      [REL]: Buffer.from('{"title":"Šef proizvoda – €"}\n'),
      'data/resumes/raw.bin': Buffer.from(Array.from({ length: 256 }, (_, i) => i)),
    }
    write(REL, 'a much longer old file that must not leave a tail behind')
    const result = await importBackupZip(root, zipOf(entries))
    for (const [rel, bytes] of Object.entries(entries)) {
      expect(fs.readFileSync(abs(rel)).equals(bytes)).toBe(true)
      expect(tempFiles(rel)).toEqual([])
    }
    expect(result).toEqual({
      ok: true, restored: Object.keys(entries), count: 3, refused: [], applications: null, verified: false,
    })
  })

  it('writes through a symlink instead of replacing it', async () => {
    write('elsewhere/real.json', OLD, 0o600)
    fs.mkdirSync(abs('data/jobs'), { recursive: true })
    fs.symlinkSync(abs('elsewhere/real.json'), abs(REL))
    await importBackupZip(root, zipOf({ [REL]: NEW }))
    expect(fs.lstatSync(abs(REL)).isSymbolicLink()).toBe(true)
    expect(fs.readFileSync(abs('elsewhere/real.json'), 'utf-8')).toBe(NEW)
    expect(modeOf('elsewhere/real.json')).toBe(0o600)
    expect(tempFiles('elsewhere/real.json')).toEqual([])
  })

  it('restores a file whose name is at the length limit', async () => {
    const rel = `data/jobs/${'a'.repeat(250)}.json`
    await importBackupZip(root, zipOf({ [rel]: NEW }))
    expect(fs.readFileSync(abs(rel), 'utf-8')).toBe(NEW)
  })
})
