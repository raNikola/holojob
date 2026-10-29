import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach } from 'vitest'
import { setFindingsRoot } from '../../../scripts/ai-findings-store.js'
import { setContactSource } from '../../../scripts/ai-redact.js'

// Every test gets its own empty findings store, so no test reads or writes the real data/ai/findings and no test sees
// another's stored answers.
//
// The same for the contacts the redaction step reads from the application store: by default that is the real
// data/applications, so a contact the owner recorded (a placeholder name such as "Name Surname") made the
// fail-closed check refuse prompts in unrelated tests. A test that needs contacts calls setContactSource itself.
const noContacts = () => ({ names: [], emails: [], phones: [], links: [] })
let dir
beforeEach(() => {
  setContactSource(noContacts)
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'findings-'))
  setFindingsRoot(path.join(dir, 'findings'))
})
afterEach(() => {
  setContactSource()
  setFindingsRoot()
  fs.rmSync(dir, { recursive: true, force: true })
})
