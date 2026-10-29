import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach } from 'vitest'
import { setFindingsRoot } from '../../../scripts/ai-findings-store.js'

// Every test gets its own empty findings store, so no test reads or writes the real data/ai/findings and no test sees
// another's stored answers.
let dir
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'findings-'))
  setFindingsRoot(path.join(dir, 'findings'))
})
afterEach(() => {
  setFindingsRoot()
  fs.rmSync(dir, { recursive: true, force: true })
})
