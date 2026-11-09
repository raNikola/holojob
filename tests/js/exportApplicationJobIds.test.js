import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { applicationJobIds, exportApplicationJobIds } from '../../scripts/export-application-job-ids.js'

describe('export of application job ids', () => {
  it('lists distinct job ids only, sorted, and skips applications with none', () => {
    const store = { applications: { a: { posting: { jobId: 'g2', title: 'Secret' } }, b: { posting: { jobId: 'g1' } }, c: { posting: { jobId: 'g1' } }, d: { posting: {} }, e: {} } }
    expect(applicationJobIds(store)).toEqual(['g1', 'g2'])
    expect(applicationJobIds(null)).toEqual([])
  })

  it('writes a private file with the ids and nothing else', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appids-'))
    fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/applications/applications.json'), JSON.stringify({ version: 1, requests: {}, applications: { x: { posting: { jobId: 'job-1', title: 'Secret Title' } } } }))
    const out = path.join(root, 'out/ids.txt')
    expect(exportApplicationJobIds(root, out)).toBe(1)
    expect(fs.readFileSync(out, 'utf-8')).toMatch(/^# store-sha256 [0-9a-f]{64}\njob-1\n$/)
    expect(fs.statSync(out).mode & 0o777).toBe(0o600)
  })

  it('writes an empty file when there is no store, so an empty list is still a list', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appids-'))
    const out = path.join(root, 'ids.txt')
    expect(exportApplicationJobIds(root, out)).toBe(0)
    expect(fs.readFileSync(out, 'utf-8')).toBe('# store-sha256 none\n')
  })
})
