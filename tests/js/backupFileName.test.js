import { afterEach, describe, expect, it, vi } from 'vitest'
import { backupFileName, importBackupZip } from '../../src/modules/backup/backupClient.js'

vi.mock('../../src/utils/apiAvailability.js', () => ({ ensureApiAvailable: async () => true }))

const realTz = process.env.TZ

afterEach(() => {
  if (realTz === undefined) delete process.env.TZ
  else process.env.TZ = realTz
  vi.unstubAllGlobals()
})

describe('backupFileName', () => {
  it('keeps the prefix and extension and adds a zero-padded date and time', () => {
    expect(backupFileName(new Date(2026, 0, 2, 3, 4, 5))).toBe('career-os-backup-2026-01-02_03-04.zip')
  })

  it('has no colons or spaces', () => {
    expect(backupFileName()).toMatch(/^career-os-backup-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.zip$/)
  })

  it('uses local time, not UTC, including across midnight', () => {
    process.env.TZ = 'Europe/Belgrade'
    expect(backupFileName(new Date('2026-11-02T23:30:00Z'))).toBe('career-os-backup-2026-11-03_00-30.zip')
  })
})

describe('restore', () => {
  it.each(['career-os-backup.zip', 'career-os-backup-2026-11-02_19-34.zip'])('sends %s the same way, by its bytes alone', async (name) => {
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ count: 1 }) }))
    vi.stubGlobal('fetch', fetchFn)
    const bytes = new Uint8Array([1, 2, 3]).buffer
    await expect(importBackupZip({ name, arrayBuffer: async () => bytes })).resolves.toEqual({ count: 1 })
    expect(fetchFn).toHaveBeenCalledOnce()
    const [url, options] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/backup/import')
    expect(options.body).toBe(bytes)
    expect(JSON.stringify(options.headers)).not.toContain(name)
  })
})
