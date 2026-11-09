import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { exportApplicationsSnapshot } from '../../scripts/export-applications-snapshot.js'

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appsnap-'))
  const dir = path.join(root, 'data/applications')
  fs.mkdirSync(path.join(dir, 'files/app-0123456789abcdef'), { recursive: true })
  fs.writeFileSync(path.join(dir, 'applications.json'), '{"version":1,"applications":{}}\n')
  fs.writeFileSync(path.join(dir, 'settings.json'), '{}\n')
  fs.writeFileSync(path.join(dir, 'files/app-0123456789abcdef/cv.pdf'), 'bytes')
  return root
}
const hash = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')

describe('applications snapshot export', () => {
  it('copies every file, writes a manifest whose hashes match, with private modes', () => {
    const root = fixture()
    const before = hash(path.join(root, 'data/applications/applications.json'))
    const result = exportApplicationsSnapshot(root)
    const manifest = JSON.parse(fs.readFileSync(path.join(result.dir, 'manifest.json'), 'utf-8'))
    expect(Object.keys(manifest.files).sort()).toEqual(['applications.json', 'files/app-0123456789abcdef/cv.pdf', 'settings.json'])
    for (const [rel, info] of Object.entries(manifest.files)) expect(hash(path.join(result.dir, rel))).toBe(info.sha256)
    expect(result.storeSha256).toBe(before)
    expect(fs.statSync(result.dir).mode & 0o777).toBe(0o700)
    expect(fs.statSync(path.join(result.dir, 'applications.json')).mode & 0o777).toBe(0o600)
    expect(fs.statSync(path.join(result.dir, 'manifest.json')).mode & 0o777).toBe(0o600)
  })

  it('leaves the source untouched and never overwrites an earlier snapshot', () => {
    const root = fixture()
    const file = path.join(root, 'data/applications/applications.json')
    const before = { sha: hash(file), mtime: fs.statSync(file).mtimeMs }
    const now = () => new Date('2026-11-09T10:00:00Z')
    exportApplicationsSnapshot(root, { now })
    expect({ sha: hash(file), mtime: fs.statSync(file).mtimeMs }).toEqual(before)
    expect(() => exportApplicationsSnapshot(root, { now })).toThrow()
  })

  it('works with no store (zero files, no store hash)', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appsnap-'))
    const result = exportApplicationsSnapshot(root)
    expect(result.fileCount).toBe(0)
    expect(result.storeSha256).toBeNull()
  })
})
