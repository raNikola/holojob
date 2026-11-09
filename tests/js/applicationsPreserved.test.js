import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import * as store from '../../scripts/application-store.js'
import { exportApplicationsSnapshot } from '../../scripts/export-applications-snapshot.js'
import { snapshotSha } from '../../scripts/application-store.js'

// The owner's four real records are server-side already (origin manual, snapshot taken at apply time). No Wave 6 path may change them.

const ids = ['a1b2c3d4e5f60718', 'b1b2c3d4e5f60718', 'c1b2c3d4e5f60718', 'd1b2c3d4e5f60718']
const job = (jobId) => ({ jobId, provider: 'greenhouse', source: 'greenhouse', title: `PM ${jobId.slice(0, 2)}`, company: 'Acme', location: 'Remote', jobUrl: `https://acme.example/jobs/${jobId}`, description: 'Own the roadmap.' })
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex')
let seq = 0

async function world() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'preserved-'))
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
  fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: {}, jobs: ids.map(job) }))
  const clock = new Date('2026-11-01T10:00:00.000Z')
  for (const jobId of ids) {
    await store.createApplication(root, {
      requestId: `req-${(seq += 1)}-${crypto.randomUUID()}`, jobId,
      attempt: { channel: 'company_site', channelDetail: '', applicationUrl: '', appliedDate: '2026-11-01', cv: { kind: 'unknown', cvLibraryId: null, label: '' } },
    }, { now: () => clock })
  }
  return root
}
const file = (root) => path.join(root, 'data/applications/applications.json')

describe('existing applications survive every Wave 6 path unchanged', () => {
  it('a migration of browser rows (applied_manually, other jobs) adds records and never rewrites an existing one', async () => {
    const root = await world()
    const before = store.loadStore(root)
    const frozen = JSON.stringify(before.applications)
    const others = ['e1b2c3d4e5f60718', 'f1b2c3d4e5f60718']
    const browserJobs = [...ids, ...others].map((jobId) => ({ ...job(jobId), status: 'applied_manually' }))
    fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: {}, jobs: browserJobs }))
    const at = () => new Date('2026-11-09T10:00:00.000Z')
    const plan = await store.previewMigration(root, { jobs: browserJobs }, { now: at })
    expect(plan.counts.created).toBe(2) // only the two jobs with no application; the four tracked ones are alreadyTracked
    expect(plan.counts.alreadyTracked).toBe(4)
    await store.migrateApplications(root, { jobs: browserJobs, confirm: true, previewSha: store.previewShaOf(browserJobs) }, { now: at })
    const after = store.loadStore(root)
    for (const [id, app] of Object.entries(before.applications)) {
      expect(JSON.stringify(after.applications[id])).toBe(JSON.stringify(app))
      expect(app.origin).toBe('manual')
      expect(app.posting.snapshotSha256).toBe(snapshotSha(app.posting))
    }
    expect(Object.keys(after.applications)).toHaveLength(6)
    expect(JSON.stringify(Object.fromEntries(Object.entries(after.applications).filter(([id]) => before.applications[id])))).toBe(frozen)
  })

  it('a preview, and a snapshot export leave the store bytes alone', async () => {
    const root = await world()
    const bytes = sha(fs.readFileSync(file(root)))
    exportApplicationsSnapshot(root)
    await store.previewMigration(root, { jobs: ids.map((jobId) => ({ ...job(jobId), status: 'applied_manually' })) }, { now: () => new Date() })
    expect(sha(fs.readFileSync(file(root)))).toBe(bytes)
  })
})
