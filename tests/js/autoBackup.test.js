// Automatic backup before a write that changes one of the four owner files (owner decision 2026-11-23). Synthetic data, temp folders only.
import fs from 'node:fs'
import crypto from 'node:crypto'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AUTO_BACKUP_FILES, BackupError, backupBeforeWrite } from '../../scripts/auto-backup.js'
import { importBackupZip } from '../../scripts/backup-handler.js'
import { writeProfileFile } from '../../scripts/save-profile.js'

let tmp
let root
beforeEach(() => { tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'auto-backup-')); root = path.join(tmp, 'data') })
afterEach(() => { fs.rmSync(tmp, { recursive: true, force: true }) })

const put = (rel, text) => { const f = path.join(root, rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, text); return f }
const versions = (name) => { try { return fs.readdirSync(path.join(root, 'backups', 'auto', name)).sort() } catch { return [] } }
const at = (n) => new Date(Date.UTC(2026, 10, 23, 10, 0, n))
const mode = (p) => fs.statSync(p).mode & 0o777

describe('what is backed up, and when', () => {
  it('the old content, before a changing write, with the right names and modes, hash-checked', () => {
    const f = put('intelligence/candidate-intelligence.json', '{"v":1}')
    const result = backupBeforeWrite(f, '{"v":2}', { dataRoot: root, now: at(1) })
    expect(path.basename(result.path)).toBe('20261123-100001.json')
    expect(fs.readFileSync(result.path, 'utf8')).toBe('{"v":1}')
    expect(result.sha256).toBe(crypto.createHash('sha256').update('{"v":1}').digest('hex'))
    expect(mode(result.path)).toBe(0o600)
    expect(mode(path.join(root, 'backups', 'auto', 'candidate-intelligence.json'))).toBe(0o700)
    expect(mode(path.join(root, 'backups', 'auto'))).toBe(0o700)
  })

  it('nothing for identical content, a missing file, another file name, or a file outside the data folder', () => {
    const f = put('jobs/scored_jobs.json', '{"a":1}')
    expect(backupBeforeWrite(f, '{"a":1}', { dataRoot: root })).toBeNull()
    expect(backupBeforeWrite(path.join(root, 'jobs', 'nothing-yet', 'scored_jobs.json'), 'x', { dataRoot: root })).toBeNull()
    const other = put('jobs/discovered_jobs.json', '{}')
    expect(backupBeforeWrite(other, '{"new":true}', { dataRoot: root })).toBeNull()
    const outside = path.join(tmp, 'scratch', 'scored_jobs.json')
    fs.mkdirSync(path.dirname(outside), { recursive: true })
    fs.writeFileSync(outside, '{}')
    expect(backupBeforeWrite(outside, '{"new":true}', { dataRoot: root })).toBeNull()
    expect(fs.existsSync(path.join(root, 'backups'))).toBe(false)
  })

  it('the profile counts as unchanged when only its save stamp differs', () => {
    const f = put('profile/candidate-profile.json', JSON.stringify({ basicProfile: { a: 1 }, meta: { updatedAt: '2026-11-22T10:00:00Z' } }, null, 2))
    const same = JSON.stringify({ basicProfile: { a: 1 }, meta: { updatedAt: '2026-11-23T10:00:00Z' } }, null, 2)
    expect(backupBeforeWrite(f, same, { dataRoot: root })).toBeNull()
    const changed = JSON.stringify({ basicProfile: { a: 2 }, meta: { updatedAt: '2026-11-23T10:00:00Z' } }, null, 2)
    expect(backupBeforeWrite(f, changed, { dataRoot: root, now: at(2) })).not.toBeNull()
  })

  it('two backups in the same second do not overwrite each other', () => {
    const f = put('profile-enrichment.json', 'one')
    backupBeforeWrite(f, 'two', { dataRoot: root, now: at(5) })
    fs.writeFileSync(f, 'two')
    backupBeforeWrite(f, 'three', { dataRoot: root, now: at(5) })
    expect(versions('profile-enrichment.json')).toEqual(['20261123-100005-2.json', '20261123-100005.json'])
  })

  it('exactly the four owner files are guarded', () => {
    expect([...AUTO_BACKUP_FILES].sort()).toEqual(['candidate-intelligence.json', 'candidate-profile.json', 'profile-enrichment.json', 'scored_jobs.json'])
  })
})

describe('how many versions are kept', () => {
  const rewrite = (rel, count) => {
    const f = put(rel, 'v0')
    for (let i = 1; i <= count; i += 1) {
      backupBeforeWrite(f, `v${i}`, { dataRoot: root, now: at(i) })
      fs.writeFileSync(f, `v${i}`)
    }
  }

  it('the last 10 per file, the oldest removed', () => {
    rewrite('intelligence/candidate-intelligence.json', 14)
    const kept = versions('candidate-intelligence.json')
    expect(kept).toHaveLength(10)
    expect(fs.readFileSync(path.join(root, 'backups/auto/candidate-intelligence.json', kept[0]), 'utf8')).toBe('v4') // v0..v3 were removed
    expect(fs.readFileSync(path.join(root, 'backups/auto/candidate-intelligence.json', kept[9]), 'utf8')).toBe('v13')
  })

  it('the last 3 for scored_jobs.json', () => {
    rewrite('jobs/scored_jobs.json', 6)
    expect(versions('scored_jobs.json')).toHaveLength(3)
  })
})

describe('a restore from a backup zip', () => {
  it('copies an owner file to data/backups/auto before it replaces it, and a failed backup stops the restore', async () => {
    const require = createRequire(import.meta.url)
    const AdmZip = require('adm-zip')
    const zipOf = (name, data) => { const zip = new AdmZip(); zip.addFile(name, Buffer.from(data)); return zip.toBuffer() }
    put('jobs/scored_jobs.json', '{"jobs":["old"]}')
    await importBackupZip(tmp, zipOf('data/jobs/scored_jobs.json', '{"jobs":["new"]}'))
    expect(fs.readFileSync(path.join(root, 'jobs/scored_jobs.json'), 'utf8')).toBe('{"jobs":["new"]}')
    const [only] = versions('scored_jobs.json')
    expect(fs.readFileSync(path.join(root, 'backups/auto/scored_jobs.json', only), 'utf8')).toBe('{"jobs":["old"]}')
    fs.rmSync(path.join(root, 'backups'), { recursive: true })
    fs.writeFileSync(path.join(root, 'backups'), 'a file where the folder should be')
    await expect(importBackupZip(tmp, zipOf('data/jobs/scored_jobs.json', '{"jobs":["newer"]}'))).rejects.toThrow(/nothing was changed/)
    expect(fs.readFileSync(path.join(root, 'jobs/scored_jobs.json'), 'utf8')).toBe('{"jobs":["new"]}')
  })
})

describe('no write without a backup', () => {
  it('a backup that cannot be written throws BackupError, and the writer leaves the file as it was', () => {
    const f = put('profile/candidate-profile.json', JSON.stringify({ basicProfile: { a: 1 } }))
    fs.writeFileSync(path.join(root, 'backups'), 'a file where the folder should be') // the backup folder cannot be created
    expect(() => backupBeforeWrite(f, '{"changed":true}', { dataRoot: root })).toThrow(BackupError)
    const before = fs.readFileSync(f)
    expect(() => writeProfileFile({ basicProfile: { a: 2 } }, f, { dataRoot: root })).toThrow(/nothing was changed/)
    expect(fs.readFileSync(f).equals(before)).toBe(true)
  })
})
