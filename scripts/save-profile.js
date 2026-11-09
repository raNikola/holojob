#!/usr/bin/env node
/**
 * Save candidate profile to data/profile/candidate-profile.json
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
export const PROFILE_PATH = path.join(ROOT, 'data/profile/candidate-profile.json')

/**
 * The one Node write of the profile file: temp file, fsync, rename (`replaceFileAtomic`), so an interrupted write leaves the old
 * file or the new one, never half of one. The modes apply only when the file or folder is created.
 */
export function writeProfileFile(profile, file = PROFILE_PATH) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: PRIVATE_DIR_MODE })
  replaceFileAtomic(file, JSON.stringify(profile, null, 2), { mode: PRIVATE_FILE_MODE })
}

export function saveProfileToDisk(profile, file = PROFILE_PATH) {
  if (!profile || typeof profile !== 'object') {
    throw new Error('Invalid profile payload')
  }
  const clone = JSON.parse(JSON.stringify(profile))
  delete clone._confidence
  delete clone._editedFields
  clone.meta = {
    ...clone.meta,
    updatedAt: new Date().toISOString(),
    profileVersion: clone.meta?.profileVersion || '1.0',
  }
  writeProfileFile(clone, file)
  return { path: file, savedAt: clone.meta.updatedAt }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  const input = fs.readFileSync(0, 'utf-8')
  const profile = JSON.parse(input)
  const result = saveProfileToDisk(profile)
  console.log(`Saved profile → ${result.path}`)
}
