import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { backupFolderName, resetProfileOnDisk } from '../../scripts/profile-reset.js'

let dataDir

const write = (rel, text) => {
  const abs = path.join(dataDir, rel)
  fs.mkdirSync(path.dirname(abs), { recursive: true })
  fs.writeFileSync(abs, text)
}
const exists = (rel) => fs.existsSync(path.join(dataDir, rel))
const NOW = new Date(2026, 10, 1, 9, 5, 7)

beforeEach(() => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-reset-'))
  write('profile/candidate-profile.json', '{"basicProfile":{"fullName":"Jane Sample"}}')
  write('profile/.gitkeep', '')
  write('profile/cvs/0123456789abcdef.pdf', '%PDF-1.4 sample')
  write('intelligence/candidate-intelligence.json', '{"meta":{}}')
  write('intelligence/project-intelligence.json', '{"projects":[]}')
  write('jobs/scored_jobs.json', '{"jobs":[1]}')
  write('applications/store.json', '{"apps":[1]}')
  write('ai/settings.json', '{"budget":5}')
  write('secrets/ai.json', '{"openai":{"key":"sk-test"}}')
  write('config/ai-settings.json', '{"provider":"ollama"}')
})
afterEach(() => fs.rmSync(dataDir, { recursive: true, force: true }))

describe('resetProfileOnDisk', () => {
  it('names the backup folder from the time', () => {
    expect(backupFolderName(NOW)).toBe('profile.bak-20261101-090507')
  })

  it('backs up the profile, CVs and candidate intelligence, then removes them', () => {
    const result = resetProfileOnDisk({ dataDir, now: NOW })
    expect(result).toEqual({ ok: true, backup: 'profile.bak-20261101-090507', moved: 3 })
    const bak = 'profile.bak-20261101-090507'
    expect(fs.readFileSync(path.join(dataDir, bak, 'profile/candidate-profile.json'), 'utf8')).toContain('Jane Sample')
    expect(exists(`${bak}/profile/cvs/0123456789abcdef.pdf`)).toBe(true)
    expect(exists(`${bak}/intelligence/candidate-intelligence.json`)).toBe(true)
    expect(exists('profile/candidate-profile.json')).toBe(false)
    expect(exists('profile/cvs')).toBe(false)
    expect(exists('intelligence/candidate-intelligence.json')).toBe(false)
    expect(exists('profile/.gitkeep')).toBe(true)
  })

  it('leaves jobs, applications, AI data, secrets, config and project intelligence alone', () => {
    resetProfileOnDisk({ dataDir, now: NOW })
    for (const rel of ['jobs/scored_jobs.json', 'applications/store.json', 'ai/settings.json', 'secrets/ai.json', 'config/ai-settings.json', 'intelligence/project-intelligence.json']) {
      expect(exists(rel), rel).toBe(true)
    }
    expect(exists('profile.bak-20261101-090507/secrets')).toBe(false)
  })

  it('is idempotent: a second call succeeds and makes no new backup', () => {
    resetProfileOnDisk({ dataDir, now: NOW })
    const again = resetProfileOnDisk({ dataDir, now: new Date(2026, 10, 1, 9, 6, 0) })
    expect(again).toEqual({ ok: true, backup: null, moved: 0 })
    expect(fs.readdirSync(dataDir).filter((n) => n.startsWith('profile.bak-'))).toHaveLength(1)
  })

  it('does not overwrite an existing backup folder with the same name', () => {
    resetProfileOnDisk({ dataDir, now: NOW })
    write('profile/candidate-profile.json', '{"second":true}')
    const second = resetProfileOnDisk({ dataDir, now: NOW })
    expect(second.backup).toBe('profile.bak-20261101-090507-2')
    expect(fs.readFileSync(path.join(dataDir, 'profile.bak-20261101-090507/profile/candidate-profile.json'), 'utf8')).toContain('Jane Sample')
  })

  it('aborts and keeps every original when the backup copy fails', () => {
    const failing = { ...fs, cpSync: () => { throw new Error('disk full: Jane Sample') } }
    const result = resetProfileOnDisk({ dataDir, now: NOW, fsImpl: failing })
    expect(result).toEqual({ ok: false, code: 'backup_failed' })
    expect(exists('profile/candidate-profile.json')).toBe(true)
    expect(exists('profile/cvs/0123456789abcdef.pdf')).toBe(true)
    expect(exists('intelligence/candidate-intelligence.json')).toBe(true)
    expect(fs.readdirSync(dataDir).some((n) => n.startsWith('profile.bak-'))).toBe(false)
  })

  it('removes nothing when the backup cannot be created', () => {
    const failing = { ...fs, mkdirSync: () => { throw new Error('read-only') } }
    expect(resetProfileOnDisk({ dataDir, now: NOW, fsImpl: failing }).ok).toBe(false)
    expect(exists('profile/candidate-profile.json')).toBe(true)
  })

  it('makes the backup before it removes anything', () => {
    const order = []
    const spy = {
      ...fs,
      cpSync: (...a) => { order.push('copy'); return fs.cpSync(...a) },
      rmSync: (...a) => { order.push('remove'); return fs.rmSync(...a) },
    }
    resetProfileOnDisk({ dataDir, now: NOW, fsImpl: spy })
    expect(order.indexOf('remove')).toBeGreaterThan(order.lastIndexOf('copy'))
  })
})
