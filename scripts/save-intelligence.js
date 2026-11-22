#!/usr/bin/env node
/**
 * Save candidate intelligence to data/intelligence/candidate-intelligence.json
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE } from './atomic-file.js'
import { backupBeforeWrite } from './auto-backup.js'
import { assertSafeToReplace, readExistingJson } from './save-guard.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
export const INTELLIGENCE_PATH = path.join(ROOT, 'data/intelligence/candidate-intelligence.json')

/**
 * The one Node write of the intelligence file. The modes apply only when the file or folder is created.
 * Before the write: the save guard may refuse it (SaveRefused, 409) and the automatic backup is made (BackupError, no write without it).
 */
export function writeIntelligenceFile(intelligence, file = INTELLIGENCE_PATH, options = {}) {
  const text = JSON.stringify(intelligence, null, 2)
  assertSafeToReplace('intelligence', readExistingJson(file), intelligence)
  backupBeforeWrite(file, text, options)
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: PRIVATE_DIR_MODE })
  fs.writeFileSync(file, text, { encoding: 'utf-8', mode: PRIVATE_FILE_MODE })
}

export function saveIntelligenceToDisk(intelligence, file = INTELLIGENCE_PATH, options = {}) {
  if (!intelligence || typeof intelligence !== 'object') {
    throw new Error('Invalid intelligence payload')
  }
  const clone = JSON.parse(JSON.stringify(intelligence))
  writeIntelligenceFile(clone, file, options)
  return { path: file, savedAt: clone.meta?.generatedAt || new Date().toISOString() }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  const input = fs.readFileSync(0, 'utf-8')
  const intelligence = JSON.parse(input)
  const result = saveIntelligenceToDisk(intelligence)
  console.log(`Saved intelligence → ${result.path}`)
}
