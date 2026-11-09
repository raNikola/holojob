import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { replaceFileAtomic } from '../../scripts/atomic-file.js'
import { saveProfileToDisk } from '../../scripts/save-profile.js'
import { isRealData } from './setup/realDataGuard.js'

const REAL_DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../data')
const PROBE = path.join(REAL_DATA, 'profile', '__guard_probe__.json')
const PROBE_DIR = path.join(REAL_DATA, '__guard_probe_dir__')

// If the guard ever fails, these tests must not leave a stray file in the real data/ folder behind. The cleanup cannot use fs (the guard
// refuses it, which is the point), so it uses rm; it only runs for a probe that exists, and then the test has already failed.
afterEach(() => {
  vi.restoreAllMocks()
  for (const target of [PROBE, PROBE_DIR]) if (fs.existsSync(target)) execFileSync('rm', ['-rf', target])
})

describe('no test can change the real data/ folder', () => {
  it('refuses every way of writing, moving, copying or removing there', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-'))
    const source = path.join(tmp, 'source.txt')
    fs.writeFileSync(source, 'x')
    const attempts = {
      writeFileSync: () => fs.writeFileSync(PROBE, 'x'),
      appendFileSync: () => fs.appendFileSync(PROBE, 'x'),
      mkdirSync: () => fs.mkdirSync(PROBE_DIR),
      renameSync: () => fs.renameSync(source, PROBE),
      copyFileSync: () => fs.copyFileSync(source, PROBE),
      createWriteStream: () => fs.createWriteStream(PROBE),
      openSync_w: () => fs.openSync(PROBE, 'w'),
      openSync_wx: () => fs.openSync(PROBE, 'wx'),
      openSync_numeric: () => fs.openSync(PROBE, fs.constants.O_WRONLY | fs.constants.O_CREAT),
      rmSync: () => fs.rmSync(path.join(REAL_DATA, 'profile', 'candidate-profile.json')),
      unlinkSync: () => fs.unlinkSync(path.join(REAL_DATA, 'profile', 'candidate-profile.json')),
      truncateSync: () => fs.truncateSync(path.join(REAL_DATA, 'profile', 'candidate-profile.json'), 0),
      chmodSync: () => fs.chmodSync(path.join(REAL_DATA, 'profile', 'candidate-profile.json'), 0o600),
      symlinkSync: () => fs.symlinkSync(source, PROBE),
    }
    for (const [name, attempt] of Object.entries(attempts)) expect(attempt, name).toThrow(/under the real data\/ folder/)
    expect(fs.existsSync(PROBE)).toBe(false)
    expect(fs.existsSync(PROBE_DIR)).toBe(false)
  })

  it('refuses the promise and callback forms, and a relative path or a URL that resolves there', async () => {
    await expect(fs.promises.writeFile(PROBE, 'x')).rejects.toThrow(/real data/)
    await expect(fs.promises.rename(PROBE, PROBE)).rejects.toThrow(/real data/)
    expect(() => fs.writeFile(PROBE, 'x', () => {})).toThrow(/real data/)
    expect(() => fs.writeFileSync(path.relative(process.cwd(), PROBE), 'x')).toThrow(/real data/)
    expect(() => fs.writeFileSync(path.join(REAL_DATA, 'profile', '..', 'profile', '__guard_probe__.json'), 'x')).toThrow(/real data/)
    expect(() => fs.writeFileSync(new URL(`file://${PROBE}`), 'x')).toThrow(/real data/)
    expect(fs.existsSync(PROBE)).toBe(false)
  })

  it('names the path relative to the repo and never anything else', () => {
    let message = ''
    try { fs.writeFileSync(PROBE, 'CANARY-CONTENT') } catch (e) { message = e.message }
    expect(message).toContain('data/profile/__guard_probe__.json')
    expect(message).not.toContain('CANARY')
  })

  it('reading is not blocked, and neither is a temp directory or a folder that only starts with "data"', () => {
    expect(() => fs.readFileSync(path.join(REAL_DATA, '..', 'package.json'))).not.toThrow()
    expect(() => fs.existsSync(PROBE)).not.toThrow()
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-ok-'))
    fs.writeFileSync(path.join(tmp, 'a.json'), '{}')
    replaceFileAtomic(path.join(tmp, 'b.json'), '{}')
    expect(isRealData(path.join(REAL_DATA, '..', 'data-other', 'x'))).toBe(false)
    expect(isRealData(path.join(os.tmpdir(), 'data', 'x'))).toBe(false)
    expect(isRealData(5)).toBe(false)
    expect(isRealData(REAL_DATA)).toBe(true)
  })

  it('the 2026-11-09 incident cannot happen again: a mocked write plus the atomic rename does not reach the real profile', () => {
    // The old tests stubbed writeFileSync and mkdirSync "to intercept" the write. The temp file was then empty and the rename real.
    vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
    vi.spyOn(fs, 'mkdirSync').mockImplementation(() => {})
    expect(() => replaceFileAtomic(PROBE, '{"a":1}', { mode: 0o600 })).toThrow(/real data/)
    expect(() => saveProfileToDisk({ basicProfile: {} })).toThrow(/real data/) // the default path is the real profile mirror
    expect(fs.existsSync(PROBE)).toBe(false)
  })
})

describe('the guard also covers modules that use named imports from node:fs', () => {
  it('refuses writes made through `import { writeFileSync } from "node:fs"` and `node:fs/promises`', async () => {
    const { writeNamed, renameNamed, writeNamedPromise } = await import('./fixtures/namedFsWriter.js')
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-named-'))
    fs.writeFileSync(path.join(tmp, 's.txt'), 'x')
    expect(() => writeNamed(PROBE)).toThrow(/real data/)
    expect(() => renameNamed(path.join(tmp, 's.txt'), PROBE)).toThrow(/real data/)
    await expect(writeNamedPromise(PROBE)).rejects.toThrow(/real data/)
    expect(fs.existsSync(PROBE)).toBe(false)
    writeNamed(path.join(tmp, 'ok.txt')) // a temp path still works
    expect(fs.existsSync(path.join(tmp, 'ok.txt'))).toBe(true)
  })
})

describe('the fingerprint guard (for spawned processes)', () => {
  it('reports added, removed and changed files by name, from stat only, and ignores pipeline files', async () => {
    const { changes, fingerprint } = await import('./setup/realDataFingerprint.js')
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fp-'))
    for (const dir of ['data/profile', 'data/applications/files', 'data/intelligence', 'data/jobs']) fs.mkdirSync(path.join(root, dir), { recursive: true })
    const put = (rel, text) => fs.writeFileSync(path.join(root, rel), text)
    put('data/profile/candidate-profile.json', '{"a":1}')
    put('data/applications/applications.json', '{}')
    put('data/intelligence/candidate-intelligence.json', '{}')
    put('data/jobs/manual_jobs.json', '{}')
    const before = fingerprint(root)
    expect(changes(before, fingerprint(root))).toEqual([])
    await new Promise((resolve) => setTimeout(resolve, 15))
    put('data/profile/candidate-profile.json', '') // the 2026-11-09 incident
    put('data/applications/files/new.pdf', 'x')
    fs.unlinkSync(path.join(root, 'data/intelligence/candidate-intelligence.json'))
    put('data/jobs/manual_jobs.json', '{}') // same size, new mtime: still a write
    put('data/jobs/scored_jobs.json', '{}') // pipeline file: not guarded
    expect(changes(before, fingerprint(root))).toEqual([
      'added: data/applications/files/new.pdf',
      'changed: data/jobs/manual_jobs.json',
      'changed: data/profile/candidate-profile.json',
      'removed: data/intelligence/candidate-intelligence.json',
    ])
  })

  it('guards the same paths as the pytest guard', async () => {
    const { GUARDED_DIRS, GUARDED_FILES } = await import('./setup/realDataFingerprint.js')
    const python = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '../python/real_data_guard.py'), 'utf8')
    const list = (name) => [...python.match(new RegExp(`${name} = \\(([^)]*)\\)`))[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
    expect(GUARDED_DIRS).toEqual(list('GUARDED_DIRS'))
    expect(GUARDED_FILES).toEqual(list('GUARDED_FILES'))
  })
})
