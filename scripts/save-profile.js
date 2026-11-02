#!/usr/bin/env node
/**
 * Save candidate profile to data/profile/candidate-profile.json
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE } from './atomic-file.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
export const PROFILE_PATH = path.join(ROOT, 'data/profile/candidate-profile.json')

/** The one Node write of the profile file. The modes apply only when the file or folder is created. */
export function writeProfileFile(profile) {
  fs.mkdirSync(path.dirname(PROFILE_PATH), { recursive: true, mode: PRIVATE_DIR_MODE })
  fs.writeFileSync(PROFILE_PATH, JSON.stringify(profile, null, 2), { encoding: 'utf-8', mode: PRIVATE_FILE_MODE })
}

export function saveProfileToDisk(profile) {
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
  writeProfileFile(clone)
  return { path: PROFILE_PATH, savedAt: clone.meta.updatedAt }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  const input = fs.readFileSync(0, 'utf-8')
  const profile = JSON.parse(input)
  const result = saveProfileToDisk(profile)
  console.log(`Saved profile → ${result.path}`)
}
