import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { checkBackupRestore, createBackupStream, importBackupZip, verifyBackupZip } from '../../scripts/backup-handler.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')
const sha = (data) => createHash('sha256').update(data).digest('hex')

let root

function write(rel, content) {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content)
}

async function exportBuffer(payload = {}) {
  const chunks = []
  for await (const c of createBackupStream(root, payload)) chunks.push(c)
  return Buffer.concat(chunks)
}

// A zip with entries replaced, added or (null) removed, the way a tampered download would be. Rebuilt from the entry
// bytes: adm-zip cannot rewrite the data descriptors archiver writes.
function patched(buffer, changes) {
  const contents = new Map(new AdmZip(buffer).getEntries().map((e) => [e.entryName, e.getData()]))
  for (const [name, data] of Object.entries(changes)) {
    if (data === null) contents.delete(name)
    else contents.set(name, Buffer.from(data))
  }
  const zip = new AdmZip()
  for (const [name, data] of contents) zip.addFile(name, data)
  return zip.toBuffer()
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-integrity-'))
  write('data/profile/candidate-profile.json', '{"name":"Fictional"}')
  write('data/jobs/scored_jobs.json', '{"jobs":[{"jobId":"a"}]}')
  write('data/analytics/runs/20261101T000000Z-r1.json', '{"status":"ok"}')
  write('data/analytics/runs/.commit-in-progress.json', '{"runId":"x"}')
  write('data/cache/llm_fit.json', '{"fit":1}')
})

afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

describe('backup manifest', () => {
  it('lists every file with its sha256 and size, includes data/analytics, leaves run-state out', async () => {
    const zip = new AdmZip(await exportBuffer())
    const manifest = JSON.parse(zip.getEntry('backup-manifest.json').getData().toString())
    expect(manifest.version).toBe('2.0')
    expect(Object.keys(manifest.files).sort()).toEqual([
      'data/analytics/runs/20261101T000000Z-r1.json',
      'data/cache/llm_fit.json',
      'data/jobs/scored_jobs.json',
      'data/profile/candidate-profile.json',
    ])
    for (const [name, meta] of Object.entries(manifest.files)) {
      const data = zip.getEntry(name).getData()
      expect(meta).toEqual({ sha256: sha(data), bytes: data.length })
    }
  })

  it('says which of the browser profile, intelligence and job list were sent, and the browser copy wins', async () => {
    const zip = new AdmZip(await exportBuffer({ jobs: { jobs: [{ jobId: 'b', status: 'kept' }] } }))
    const manifest = JSON.parse(zip.getEntry('backup-manifest.json').getData().toString())
    expect(manifest.browserState).toEqual({ profile: false, intelligence: false, jobs: true })
    expect(zip.getEntry('data/jobs/scored_jobs.json').getData().toString()).toContain('"kept"')
    expect(zip.getEntries().filter((e) => e.entryName === 'data/jobs/scored_jobs.json')).toHaveLength(1)
    expect(manifest.files['data/jobs/scored_jobs.json'].sha256).toBe(sha(zip.getEntry('data/jobs/scored_jobs.json').getData()))
  })
})

describe('verify and tamper detection', () => {
  it('passes an untouched archive', async () => {
    const result = verifyBackupZip(await exportBuffer())
    expect(result).toMatchObject({ ok: true, hashed: true, files: 4, problems: [] })
  })

  it('catches a changed file, a deleted file, an added file and a broken manifest', async () => {
    const good = await exportBuffer()
    expect(verifyBackupZip(patched(good, { 'data/cache/llm_fit.json': '{"fit":2}' })).problems)
      .toEqual([{ name: 'data/cache/llm_fit.json', reason: 'hash differs' }])
    expect(verifyBackupZip(patched(good, { 'data/cache/llm_fit.json': null })).problems)
      .toEqual([{ name: 'data/cache/llm_fit.json', reason: 'missing from the archive' }])
    expect(verifyBackupZip(patched(good, { 'data/profile/extra.json': '{}' })).problems)
      .toEqual([{ name: 'data/profile/extra.json', reason: 'not in the manifest' }])
    expect(verifyBackupZip(patched(good, { 'backup-manifest.json': '{not json' })).ok).toBe(false)
  })

  it('refuses to restore a tampered archive and writes nothing', async () => {
    const tampered = patched(await exportBuffer(), { 'data/jobs/scored_jobs.json': '{"jobs":[]}' })
    const target = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-target-'))
    try {
      await expect(importBackupZip(target, tampered)).rejects.toThrow(/does not match its manifest, nothing was restored/)
      expect(fs.readdirSync(target)).toEqual([])
    } finally {
      fs.rmSync(target, { recursive: true, force: true })
    }
  })

  it('still restores an archive from before manifests, marked unverified', async () => {
    const zip = new AdmZip()
    zip.addFile('data/cache/llm_fit.json', Buffer.from('{}'))
    const target = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-target-'))
    try {
      expect(await importBackupZip(target, zip.toBuffer())).toMatchObject({ ok: true, verified: false, count: 1 })
    } finally {
      fs.rmSync(target, { recursive: true, force: true })
    }
  })
})

describe('restore check in a throwaway directory', () => {
  it('passes, compares every restored file by hash, and removes its directory', async () => {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-base-'))
    try {
      const before = fs.readFileSync(path.join(root, 'data/jobs/scored_jobs.json'))
      const report = await checkBackupRestore(await exportBuffer(), { tmpBase: base })
      expect(report).toMatchObject({ ok: true, hashed: true, checked: 4, merged: 0, problems: [] })
      expect(fs.readdirSync(base)).toEqual([])
      expect(fs.readFileSync(path.join(root, 'data/jobs/scored_jobs.json'))).toEqual(before) // the source tree is untouched
    } finally {
      fs.rmSync(base, { recursive: true, force: true })
    }
  })

  it('fails on a tampered archive without restoring, and on one without hashes', async () => {
    const good = await exportBuffer()
    const bad = await checkBackupRestore(patched(good, { 'data/cache/llm_fit.json': 'x' }))
    expect(bad).toMatchObject({ ok: false, checked: 0 })
    const old = new AdmZip()
    old.addFile('data/cache/llm_fit.json', Buffer.from('{}'))
    expect(await checkBackupRestore(old.toBuffer())).toMatchObject({ hashed: false })
  })
})
