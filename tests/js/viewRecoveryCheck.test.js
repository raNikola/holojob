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

function syntheticRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-recovery-src-'))
  for (const name of ['scripts', 'python', 'src', 'node_modules', 'package.json']) fs.symlinkSync(path.join(REPO, name), path.join(root, name))
  const jobs = path.join(root, 'data/jobs')
  fs.mkdirSync(jobs, { recursive: true })
  const ledger = {
    generation: 1,
    jobs: {},
    lastImport: {
      runId: 'r1',
      at: '2026-11-03T10:00:00+00:00',
      meta: { rawCount: 0, dedupedCount: 0, sourceRunId: 'r1', searchTerms: [], locations: [], remoteFilters: [], country: 'rs', providers: [], providerCounts: {}, history: {} },
    },
  }
  fs.writeFileSync(path.join(jobs, 'job_history.json'), JSON.stringify(ledger, null, 2))
  const made = spawnSync(python, ['-c', `
import importlib.util, json
s = importlib.util.spec_from_file_location('vg', '${REPO}/python/job_scoring/view_guard.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
l = json.load(open('${jobs}/job_history.json'))
open('${jobs}/discovered_jobs.json', 'w').write(m.serialize_view(m.derive_view(l)))`])
  expect(made.status).toBe(0)
  return root
}

describe.skipIf(!python)('check-view-recovery', () => {
  it('regenerates a stale view, then refuses with 503 when the ledger is unreadable, with the production host guard configured', async () => {
    const root = syntheticRoot()
    const saved = process.env.CAREER_OS_ALLOWED_ORIGINS
    process.env.CAREER_OS_ALLOWED_ORIGINS = 'https://careeros.void,http://localhost:3073' // as the container's .env
    try {
      const lines = []
      const result = await runCheck({ sourceRoot: root, python, log: (l) => lines.push(l) })
      expect(lines.join('\n')).toContain('Host: careeros.void')
      expect(lines.join('\n')).toContain('RESULT: ALL PASS')
      expect(result.ok).toBe(true)
      expect(result.environmentFailure).toBe(false)
      expect(result.liveUnchanged).toBe(true)
      expect(result.steps.length).toBeGreaterThanOrEqual(8)
    } finally {
      if (saved === undefined) delete process.env.CAREER_OS_ALLOWED_ORIGINS
      else process.env.CAREER_OS_ALLOWED_ORIGINS = saved
      fs.rmSync(root, { recursive: true, force: true })
    }
  }, 60000)

  it('reports a 403 from the host guard as an ENVIRONMENT failure, not as a recovery failure', async () => {
    const root = syntheticRoot()
    const saved = process.env.CAREER_OS_ALLOWED_ORIGINS
    process.env.CAREER_OS_ALLOWED_ORIGINS = 'https://careeros.void'
    try {
      const lines = []
      const result = await runCheck({ sourceRoot: root, python, host: 'not-allowed.example', log: (l) => lines.push(l) })
      const text = lines.join('\n')
      expect(result.ok).toBe(false)
      expect(result.environmentFailure).toBe(true)
      expect(text).toContain('ENVIRONMENT: the request guard refused')
      expect(text).toContain('RESULT: ENVIRONMENT FAILURE')
      expect(text).not.toMatch(/FAIL {2}\((a|b|c)\)/)
      expect(result.liveUnchanged).toBe(true)
    } finally {
      if (saved === undefined) delete process.env.CAREER_OS_ALLOWED_ORIGINS
      else process.env.CAREER_OS_ALLOWED_ORIGINS = saved
      fs.rmSync(root, { recursive: true, force: true })
    }
  }, 60000)
})
