/**
 * Reads the fact gate's verdict on a generated document (written by python/resume_generator/verdicts.py, same format).
 * The application store asks here before it copies a generated document into an application, so a document that was never
 * judged, failed the gate, or was changed after it was judged cannot be attached. This module only reads.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

/** Must equal GATE_VERSION in verdicts.py (a test compares them). A verdict from an older gate is not trusted. */
export const GATE_VERSION = 1

export function verdictPath(dir, fileName) {
  return path.join(dir, `.${fileName}.verdict.json`)
}

/**
 * @returns {{ ok: true, sha256: string } | { ok: false, code: 'missing'|'changed'|'failed'|'old_gate', reason: string, issues?: string[] }}
 */
export function checkDocumentVerdict(dir, fileName) {
  let body
  try {
    body = JSON.parse(fs.readFileSync(verdictPath(dir, fileName), 'utf-8'))
  } catch {
    return { ok: false, code: 'missing', reason: 'This document has not passed the automatic checks yet, so it cannot be attached. Generate it again, or re-check it (python/resume_generator/recheck_documents.py).' }
  }
  let sha
  try {
    sha = crypto.createHash('sha256').update(fs.readFileSync(path.join(dir, fileName))).digest('hex')
  } catch {
    return { ok: false, code: 'missing', reason: 'The document file cannot be read.' }
  }
  if (!body || body.file !== fileName || body.sha256 !== sha) {
    return { ok: false, code: 'changed', reason: 'This document changed after the automatic checks, so it cannot be attached. Generate it again.' }
  }
  if (!Number.isInteger(body.gateVersion) || body.gateVersion < GATE_VERSION) {
    return { ok: false, code: 'old_gate', reason: 'This document was checked by an older version of the automatic checks. Generate it again, or re-check it.' }
  }
  if (body.passed !== true) {
    const issues = Array.isArray(body.issues) ? body.issues.slice(0, 20) : []
    return { ok: false, code: 'failed', reason: 'This document did not pass the automatic checks, so it cannot be attached.', issues }
  }
  return { ok: true, sha256: sha }
}
