/**
 * Stored copies of the CVs the candidate uploads (data/profile/cvs/<id>.pdf).
 * Kept apart from data/resumes/<jobId>/, which holds the tailored per-job résumés.
 * The id is made here and is the only thing a request can name: no path, no
 * file name from the client ever reaches the filesystem.
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, replaceFileAtomic } from './atomic-file.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const CVS_DIR = path.join(path.resolve(__dirname, '..'), 'data/profile/cvs')
export const MAX_CV_BYTES = 10 * 1024 * 1024

const ID_PATTERN = /^[a-f0-9]{16}$/

export function isCvId(id) {
  return typeof id === 'string' && ID_PATTERN.test(id)
}

export function cvFilePath(id, dir = CVS_DIR) {
  if (!isCvId(id)) throw new Error('Invalid CV id')
  return path.join(dir, `${id}.pdf`)
}

export function saveCvFile(buffer, dir = CVS_DIR) {
  if (!buffer?.length) throw new Error('Empty file')
  if (buffer.length > MAX_CV_BYTES) throw new Error('File is too large. Maximum size is 10 MB.')
  if (buffer.subarray(0, 5).toString('latin1') !== '%PDF-') throw new Error('Please upload a PDF file.')
  fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
  const id = crypto.randomBytes(8).toString('hex')
  replaceFileAtomic(cvFilePath(id, dir), buffer, { mode: PRIVATE_FILE_MODE })
  return { id, size: buffer.length }
}

export function deleteCvFile(id, dir = CVS_DIR) {
  const file = cvFilePath(id, dir)
  if (!fs.existsSync(file)) return false
  fs.unlinkSync(file)
  return true
}
