import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { applicationIdCoverage, applicationJobIds, exportApplicationJobIds, urlKeyCoverage } from '../../scripts/export-application-job-ids.js'

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
    expect(fs.readFileSync(out, 'utf-8')).toMatch(/^# store-sha256 [0-9a-f]{64}\n# jobid-less-applications 0\n# ledger-sha256 none\njob-1\n$/)
    expect(fs.statSync(out).mode & 0o777).toBe(0o600)
  })

  it('writes an empty file when there is no store, so an empty list is still a list', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appids-'))
    const out = path.join(root, 'ids.txt')
    expect(exportApplicationJobIds(root, out)).toBe(0)
    expect(fs.readFileSync(out, 'utf-8')).toBe('# store-sha256 none\n# jobid-less-applications 0\n# ledger-sha256 none\n')
  })

  describe('applications without a job id', () => {
    const ledgerRow = (jobUrl, title = 'T', company = 'C', location = 'L') => ({ job: { jobUrl, title, company, location } })
    const world = () => {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), 'appids-'))
      fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
      fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
      const posting = (p) => ({ posting: p })
      fs.writeFileSync(path.join(root, 'data/applications/applications.json'), JSON.stringify({ version: 1, requests: {}, applications: {
        a: posting({ jobId: 'led-1', url: 'https://x.example/a' }),
        b: posting({ jobId: null, url: 'https://X.example/b/?utm_source=z#top', title: 'Secret', company: 'Co' }),
        c: { posting: { company: 'Acme d.o.o.', title: 'Product Manager', location: 'Niš' }, voided: true },
        d: posting({ jobId: null, url: 'https://nowhere.example/none' }),
      } }))
      fs.writeFileSync(path.join(root, 'data/jobs/job_history.json'), JSON.stringify({ jobs: {
        'led-1': ledgerRow('https://x.example/a'),
        'led-2': ledgerRow('https://x.example/b'),
        'led-3': ledgerRow('', 'product manager', 'ACME', 'nis'),
        'led-4': ledgerRow('https://x.example/other'),
      } }))
      return root
    }

    it('counts applications with a null or missing job id and the ledger rows they match by URL or posting key, counts only', () => {
      const counts = applicationIdCoverage(world())
      expect(counts).toEqual({ applications: 4, jobIdless: 3, matchedApplications: 2, matchedLedgerRows: 2 })
    })

    it('matches with the store normaliser (utm and trailing slash ignored, legal suffix and diacritics folded)', () => {
      const result = urlKeyCoverage(JSON.parse(fs.readFileSync(path.join(world(), 'data/applications/applications.json'), 'utf-8')),
        { jobs: { r1: ledgerRow('https://x.example/b'), r2: ledgerRow('', 'Product Manager', 'Acme', 'Nis') } })
      expect(result.matchedIds).toEqual(['r1', 'r2'])
    })

    it('the export lists the URL-matched ledger ids and records the count and the ledger hash; the check writes nothing', () => {
      const root = world()
      const before = fs.readdirSync(path.join(root, 'data'), { recursive: true }).sort()
      applicationIdCoverage(root)
      expect(fs.readdirSync(path.join(root, 'data'), { recursive: true }).sort()).toEqual(before)
      const out = path.join(root, 'out/ids.txt')
      expect(exportApplicationJobIds(root, out)).toBe(3)
      const text = fs.readFileSync(out, 'utf-8')
      expect(text).toMatch(/^# store-sha256 [0-9a-f]{64}\n# jobid-less-applications 3\n# ledger-sha256 [0-9a-f]{64}\n/)
      expect(text.split('\n').filter((l) => l && !l.startsWith('#'))).toEqual(['led-1', 'led-2', 'led-3'])
      expect(text).not.toContain('Secret')
    })
  })
})
