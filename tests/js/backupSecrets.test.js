import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createBackupStream, importBackupZip } from '../../scripts/backup-handler.js'
import { isSecretPath, safeRelativePath } from '../../scripts/secret-paths.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')
const CANARY = 'SECRET-CANARY-7f3a9c1d'

let root

function write(rel, content) {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content)
}

async function exportZip(payload = {}) {
  const chunks = []
  for await (const c of createBackupStream(root, payload)) chunks.push(c)
  return new AdmZip(Buffer.concat(chunks))
}

function zipOf(entries) {
  const zip = new AdmZip()
  for (const [name, data] of Object.entries(entries)) zip.addFile(name, Buffer.from(data))
  return zip.toBuffer()
}

// adm-zip cleans entry names when adding them, so a hostile archive is made by patching same-length names into the bytes.
function hostileZip(entries) {
  const names = Object.keys(entries)
  const placeholders = names.map((n, i) => `P${i}${'Q'.repeat(Math.max(0, n.length - 2))}`.slice(0, n.length))
  const zip = new AdmZip()
  names.forEach((n, i) => zip.addFile(placeholders[i], Buffer.from(entries[n])))
  const buf = zip.toBuffer()
  names.forEach((n, i) => {
    let at = buf.indexOf(placeholders[i], 0, 'latin1')
    while (at !== -1) {
      buf.write(n, at, 'latin1')
      at = buf.indexOf(placeholders[i], at + n.length, 'latin1')
    }
  })
  return buf
}

beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-')) })
afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })

describe('isSecretPath', () => {
  it('flags credentials by directory and by name', () => {
    for (const p of [
      'data/secrets/ai.json', 'data/secrets', 'claude-config/.credentials.json', '.env', 'config/.env.local',
      'data/outreach/linkedin_session.json', 'data/outreach/li_at.txt', 'data/config/api-key.json', 'data/config/tokens.json',
      'data/config/cookies.json', 'data/config/credentials.json', 'data/x/server.pem', 'data/x/id_rsa', 'data/x/private.key',
      'data/config/api_keys.json', 'DATA/Secrets/ai.json', 'data/config/password.txt',
    ]) expect(isSecretPath(p), p).toBe(true)
  })

  it('treats unsafe paths as secret and lets ordinary data through', () => {
    for (const p of ['data/../etc/passwd', '/etc/passwd', 'C:/x', 'data\\..\\x']) expect(isSecretPath(p), p).toBe(true)
    for (const p of [
      'data/profile/candidate-profile.json', 'data/jobs/scored_jobs.json', 'data/applications/applications.json',
      'data/config/sources.json', 'data/outreach/abc/contacts.json', 'data/resumes/j1/Acme_Resume.pdf', 'data/keywords.json',
    ]) expect(isSecretPath(p), p).toBe(false)
  })

  it('normalises relative paths and refuses traversal', () => {
    expect(safeRelativePath('./data//a/./b')).toBe('data/a/b')
    expect(safeRelativePath('data/a/../b')).toBeNull()
    expect(safeRelativePath('')).toBeNull()
    expect(safeRelativePath('a\0b')).toBeNull()
  })
})

describe('backup export', () => {
  it('leaves out secret-looking files and carries no canary', async () => {
    write('data/profile/candidate-profile.json', '{"name":"x"}')
    write('data/outreach/abc/contacts.json', '[]')
    write('data/outreach/linkedin_session.json', JSON.stringify({ li_at: CANARY }))
    write('data/outreach/abc/cookies.json', CANARY)
    write('data/cache/api_key.txt', CANARY)
    write('data/secrets/ai.json', CANARY)
    write('data/config/tokens.json', CANARY)
    write('.env', `OPENAI_API_KEY=${CANARY}`)
    write('claude-config/.credentials.json', CANARY)
    const zip = await exportZip({ profile: { name: 'x' } })
    const names = zip.getEntries().map((e) => e.entryName)
    expect(names).toContain('data/profile/candidate-profile.json')
    expect(names).toContain('data/outreach/abc/contacts.json')
    for (const bad of ['linkedin_session', 'cookies', 'api_key', 'secrets', 'tokens', '.env', 'claude-config']) {
      expect(names.filter((n) => n.includes(bad)), bad).toEqual([])
    }
    for (const entry of zip.getEntries()) expect(entry.getData().toString('utf-8')).not.toContain(CANARY)
  })
})

describe('backup restore', () => {
  it('restores ordinary data entries', async () => {
    const result = await importBackupZip(root, zipOf({ 'backup-manifest.json': '{}', 'data/profile/candidate-profile.json': '{"a":1}' }))
    expect(result.restored).toEqual(['data/profile/candidate-profile.json'])
    expect(result.refused).toEqual([])
    expect(fs.readFileSync(path.join(root, 'data/profile/candidate-profile.json'), 'utf-8')).toBe('{"a":1}')
  })

  it('refuses the whole archive for a ".." path, writing nothing', async () => {
    const outside = path.join(path.dirname(root), `escaped-${path.basename(root)}.txt`)
    const buf = hostileZip({ 'data/profile/ok.json': '{}', [`data/../../${path.basename(outside)}`]: 'x' })
    await expect(importBackupZip(root, buf)).rejects.toThrow(/unsafe path/)
    expect(fs.existsSync(outside)).toBe(false)
    expect(fs.existsSync(path.join(root, 'data/profile/ok.json'))).toBe(false)
  })

  it('refuses an absolute path and a ".." outside data/', async () => {
    expect(new AdmZip(hostileZip({ '/tmp/x.json': 'x' })).getEntries()[0].entryName).toBe('/tmp/x.json')
    await expect(importBackupZip(root, hostileZip({ '/tmp/x.json': 'x' }))).rejects.toThrow(/unsafe path/)
    await expect(importBackupZip(root, hostileZip({ '../x.json': 'x' }))).rejects.toThrow(/unsafe path/)
  })

  it('skips data/secrets/ and secret-named files, listing them as refused', async () => {
    const result = await importBackupZip(root, zipOf({
      'data/secrets/ai.json': CANARY,
      'data/config/tokens.json': CANARY,
      'data/outreach/linkedin_session.json': CANARY,
      'data/config/sources.json': '{}',
    }))
    expect(result.refused.sort()).toEqual(['data/config/tokens.json', 'data/outreach/linkedin_session.json', 'data/secrets/ai.json'])
    expect(result.restored).toEqual(['data/config/sources.json'])
    expect(fs.existsSync(path.join(root, 'data/secrets'))).toBe(false)
    expect(fs.existsSync(path.join(root, 'data/outreach'))).toBe(false)
  })
})
