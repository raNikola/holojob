// The Jobs-list rules are shared by the browser and the Node server (docs/redesign/JOBS_LIST_SERVER_PLAN.md, owner decision: one source of rules, no copy).
// Vite resolves a bare JSON import or an extensionless import; Node 20 does not, and the server would fail at start. This loads the modules in a plain
// Node process, as the server will, and fails with Node's own error. P0 found two such breaks (a JSON import without an attribute, and imports with no
// ".js"); this keeps them fixed.
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../src')
const SHARED = [
  'modules/jobs/jobListQuery.js',
  'modules/jobs/jobFilters.js',
  'modules/jobs/fitTier.js',
  'modules/jobs/jobTableModel.js',
  'modules/jobs/jobListView.js',
  'modules/jobs/allAds.js',
  'modules/jobs/jobHistory.js',
  'modules/jobs/jobStats.js',
  'modules/jobs/jobStorage.js',
  'modules/jobs/jobStateClient.js',
  'modules/applications/trackingView.js',
  'modules/applications/appliedFilter.js',
]

describe('the shared Jobs-list modules load in plain Node', () => {
  it.each(SHARED)('%s', (file) => {
    const url = `file://${path.join(SRC, file)}`
    const out = execFileSync(process.execPath, ['--input-type=module', '-e', `await import(${JSON.stringify(url)}); console.log('loaded')`], { encoding: 'utf8', timeout: 20000 })
    expect(out.trim()).toBe('loaded')
  })
})
