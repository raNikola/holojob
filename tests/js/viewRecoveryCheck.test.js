// scripts/check-view-recovery.js against a synthetic source root (never the real data/): the Node route rebuilds a stale view and
// answers 503 view_unrecoverable when the ledger cannot be read. Needs a Python 3 that can run view_guard.py; skipped without one.
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { runCheck } from '../../scripts/check-view-recovery.js'

const REPO = path.resolve(import.meta.dirname, '../..')
const python = [path.join(REPO, '.venv/bin/python'), '/usr/bin/python3'].find(
  (p) => fs.existsSync(p) && spawnSync(p, ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)']).status === 0,
)

describe.skipIf(!python)('check-view-recovery', () => {
  it('regenerates a stale view, then refuses with 503 when the ledger is unreadable, and leaves the source files alone', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-recovery-src-'))
    try {
      for (const name of ['scripts', 'python', 'src', 'node_modules', 'package.json']) fs.symlinkSync(path.join(REPO, name), path.join(root, name))
      const jobs = path.join(root, 'data/jobs')
      fs.mkdirSync(jobs, { recursive: true })
      const ledger = { generation: 1, jobs: {}, lastImport: { runId: 'r1', at: '2026-11-03T10:00:00+00:00', meta: { rawCount: 0, dedupedCount: 0, sourceRunId: 'r1', searchTerms: [], locations: [], remoteFilters: [], country: 'rs', providers: [], providerCounts: {}, history: {} } } }
      fs.writeFileSync(path.join(jobs, 'job_history.json'), JSON.stringify(ledger, null, 2))
      const check = spawnSync(python, ['-c', `
import importlib.util, sys, json
s = importlib.util.spec_from_file_location('vg', '${REPO}/python/job_scoring/view_guard.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
l = json.load(open('${jobs}/job_history.json'))
open('${jobs}/discovered_jobs.json', 'w').write(m.serialize_view(m.derive_view(l)))`])
      expect(check.status).toBe(0)
      const lines = []
      const result = await runCheck({ sourceRoot: root, python, log: (l) => lines.push(l) })
      expect(lines.join('\n')).toContain('RESULT: ALL PASS')
      expect(result.ok).toBe(true)
      expect(result.liveUnchanged).toBe(true)
      expect(result.steps.length).toBeGreaterThanOrEqual(8)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  }, 60000)
})
