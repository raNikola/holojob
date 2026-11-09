import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { GATE_VERSION, verdictPath } from '../../../scripts/document-verdicts.js'

/** Writes the fact gate's verdict for a file that exists in `dir`, as python/resume_generator/verdicts.py would. */
export function writeVerdict(dir, fileName, { passed = true, issues = [], gateVersion = GATE_VERSION, sha256 } = {}) {
  const sha = sha256 ?? crypto.createHash('sha256').update(fs.readFileSync(path.join(dir, fileName))).digest('hex')
  fs.writeFileSync(verdictPath(dir, fileName), JSON.stringify({ file: fileName, sha256: sha, passed, issues, gateVersion, checkedAt: new Date().toISOString() }))
}
