import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyImport, assertUnionOnly, exportBrowserState, loadState, mergeStateFromBackup, patchState, previewImport,
} from '../../scripts/job-state-store.js'
import { exportProtectIds, protectedJobIds } from '../../scripts/export-protect-ids.js'

let root
let tick
const now = () => new Date(Date.UTC(2026, 10, 9, 10, 0, tick++))
const stateFile = () => path.join(root, 'data/jobs/job-state.json')
const row = (n, extra = {}) => ({ jobId: `job${n}`, key: `url:https://acme.example/${n}`, status: 'new', keep: false, ...extra })
const KEPT = row(1, { keep: true })
const SAVED = row(2, { status: 'saved' })

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'jobstate-'))
  tick = 0
})

describe('single-entry writes', () => {
  it('merges status and keep, creates the file privately, and a stale base answers 409 without writing', async () => {
    const first = await patchState(root, { key: KEPT.key, jobId: KEPT.jobId, patch: { keep: true } }, { now })
    expect(first.entry).toMatchObject({ status: 'new', keep: true })
    expect(fs.statSync(stateFile()).mode & 0o777).toBe(0o600)
    const bytes = fs.readFileSync(stateFile())
    await expect(patchState(root, { key: SAVED.key, jobId: SAVED.jobId, patch: { status: 'saved' }, baseSha256: 'none' }, { now }))
      .rejects.toMatchObject({ status: 409, extra: { code: 'stale' } })
    expect(fs.readFileSync(stateFile())).toEqual(bytes)
    const ok = await patchState(root, { key: SAVED.key, jobId: SAVED.jobId, patch: { status: 'saved' }, baseSha256: first.sha256 }, { now })
    expect(ok.entry.statusAt).not.toBeNull()
  })

  it('refuses applied_manually, unknown fields and bad keys; a no-op write leaves the bytes alone', async () => {
    for (const body of [
      { key: KEPT.key, jobId: 'job1', patch: { status: 'applied_manually' } },
      { key: KEPT.key, jobId: 'job1', patch: { notes: 'x' } },
      { key: 'nope', jobId: 'job1', patch: { keep: true } },
      { key: KEPT.key, jobId: 'bad id', patch: { keep: true } },
      { key: KEPT.key, jobId: 'job1', patch: {} },
    ]) await expect(patchState(root, body, { now })).rejects.toMatchObject({ status: 400 })
    expect(fs.existsSync(stateFile())).toBe(false)
    await patchState(root, { key: KEPT.key, jobId: 'job1', patch: { keep: true } }, { now })
    const before = fs.readFileSync(stateFile())
    const again = await patchState(root, { key: KEPT.key, jobId: 'job1', patch: { keep: true } }, { now })
    expect(again.changed).toBe(false)
    expect(fs.readFileSync(stateFile())).toEqual(before)
  })

  it('refuses to write over an unreadable file', async () => {
    fs.mkdirSync(path.dirname(stateFile()), { recursive: true })
    fs.writeFileSync(stateFile(), '{broken')
    await expect(patchState(root, { key: KEPT.key, jobId: 'job1', patch: { keep: true } }, { now })).rejects.toMatchObject({ status: 500 })
    expect(fs.readFileSync(stateFile(), 'utf-8')).toBe('{broken')
  })
})

describe('browser state export and the union import', () => {
  const rows = [KEPT, SAVED, row(3), row(4, { status: 'applied_manually' }), { ...row(5), jobId: 'bad id' }]

  it('exports ids and flags only, privately, and counts what it dropped', () => {
    const out = exportBrowserState(root, { rows: [{ ...KEPT, title: 'Secret title', notes: 'private' }, ...rows.slice(1)] }, { now })
    const text = fs.readFileSync(path.join(root, out.path), 'utf-8')
    expect(out.rows).toBe(4)
    expect(out.invalid).toBe(1)
    expect(text).not.toMatch(/Secret|private|title|notes/)
    expect(fs.statSync(path.join(root, out.path)).mode & 0o777).toBe(0o600)
  })

  it('preview writes nothing and the plan balances', () => {
    const plan = previewImport(root, { rows })
    expect(plan.counts).toMatchObject({ scanned: 4, ignored: 2, appliedInBrowser: 1, toAdd: 2, alreadyThere: 0, conflicts: 0 })
    expect(plan.invalid).toBe(1)
    expect(fs.existsSync(stateFile())).toBe(false)
    expect(fs.existsSync(path.join(root, 'data/backups'))).toBe(false)
  })

  it('apply needs confirm and the preview hash; a changed server state invalidates the preview', async () => {
    const { previewSha } = previewImport(root, { rows })
    await expect(applyImport(root, { rows, previewSha })).rejects.toThrow(/confirm/)
    await expect(applyImport(root, { rows, confirm: true, previewSha: 'x' })).rejects.toThrow(/previewSha/)
    await patchState(root, { key: row(9).key, jobId: 'job9', patch: { keep: true } }, { now })
    await expect(applyImport(root, { rows, confirm: true, previewSha })).rejects.toThrow(/previewSha/)
    expect(Object.keys(loadState(root).doc.jobs)).toEqual([row(9).key])
  })

  it('writes the union after a backup, never changes or deletes a server entry, lists conflicts, and is idempotent', async () => {
    await patchState(root, { key: SAVED.key, jobId: SAVED.jobId, patch: { status: 'rejected' } }, { now }) // the server disagrees with the browser
    await patchState(root, { key: row(9).key, jobId: 'job9', patch: { keep: true } }, { now }) // a server-only entry
    const before = loadState(root).doc
    const { previewSha, conflicts } = previewImport(root, { rows })
    expect(conflicts).toEqual([{ jobId: 'job2', fields: ['status'], kept: 'server' }])
    const done = await applyImport(root, { rows, confirm: true, previewSha }, { now })
    expect(done.changed).toBe(true)
    const after = loadState(root).doc
    assertUnionOnly(before, after)
    expect(after.jobs[SAVED.key].status).toBe('rejected')
    expect(after.jobs[row(9).key]).toEqual(before.jobs[row(9).key])
    expect(after.jobs[KEPT.key]).toMatchObject({ jobId: 'job1', keep: true })
    expect(after.jobs[row(3).key]).toBeUndefined() // new and not kept: nothing to carry
    const backup = path.join(root, done.backupPath)
    expect(JSON.parse(fs.readFileSync(path.join(backup, 'job-state.json'), 'utf-8'))).toEqual(before)
    expect(fs.existsSync(path.join(backup, 'browser-state.json'))).toBe(true)

    const second = previewImport(root, { rows })
    expect(second.counts.toAdd).toBe(0)
    const bytes = fs.readFileSync(stateFile())
    expect((await applyImport(root, { rows, confirm: true, previewSha: second.previewSha }, { now })).changed).toBe(false)
    expect(fs.readFileSync(stateFile())).toEqual(bytes)
  })

  it('a backup that cannot be written aborts and writes no state', async () => {
    fs.mkdirSync(path.join(root, 'data'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/backups'), 'a file where the folder should be')
    const { previewSha } = previewImport(root, { rows })
    await expect(applyImport(root, { rows, confirm: true, previewSha }, { now })).rejects.toThrow(/Backup failed/)
    expect(fs.existsSync(stateFile())).toBe(false)
  })

  it('assertUnionOnly rejects a changed or missing entry', () => {
    const prev = { jobs: { a: { jobId: 'j', status: 'new', statusAt: null, keep: true } } }
    expect(() => assertUnionOnly(prev, { jobs: {} })).toThrow(/union/)
    expect(() => assertUnionOnly(prev, { jobs: { a: { ...prev.jobs.a, keep: false } } })).toThrow(/union/)
    expect(() => assertUnionOnly(prev, { jobs: { ...prev.jobs, b: {} } })).not.toThrow()
  })
})

describe('restore and the prune id export', () => {
  it('a restored job-state adds missing keys and never replaces a live entry', async () => {
    await patchState(root, { key: KEPT.key, jobId: 'job1', patch: { keep: false } }, { now })
    const archived = { version: 1, updatedAt: null, jobs: {
      [KEPT.key]: { jobId: 'job1', status: 'saved', statusAt: null, keep: true },
      [SAVED.key]: { jobId: 'job2', status: 'saved', statusAt: null, keep: false },
    } }
    expect(mergeStateFromBackup(root, Buffer.from(JSON.stringify(archived)), { now })).toEqual({ added: 1, kept: 1 })
    const doc = loadState(root).doc
    expect(doc.jobs[KEPT.key]).toMatchObject({ status: 'new', keep: false })
    expect(doc.jobs[SAVED.key].status).toBe('saved')
    expect(mergeStateFromBackup(root, Buffer.from('nope'))).toEqual({ refused: 'not valid JSON' })
  })

  it('exports ids of kept or acted-on entries only, privately', async () => {
    await patchState(root, { key: KEPT.key, jobId: 'job1', patch: { keep: true } }, { now })
    await patchState(root, { key: SAVED.key, jobId: 'job2', patch: { status: 'saved' } }, { now })
    await patchState(root, { key: row(3).key, jobId: 'job3', patch: { status: 'new' } }, { now })
    expect(protectedJobIds(loadState(root).doc)).toEqual(['job1', 'job2'])
    const out = path.join(root, 'out/protect.txt')
    expect(exportProtectIds(root, out)).toBe(2)
    expect(fs.readFileSync(out, 'utf-8')).toBe('job1\njob2\n')
    expect(fs.statSync(out).mode & 0o777).toBe(0o600)
  })
})
