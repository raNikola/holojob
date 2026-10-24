import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { cvFilePath, deleteCvFile, isCvId, saveCvFile } from '../../scripts/cv-store.js'

const pdf = Buffer.from('%PDF-1.4\nbody')
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'cvs-'))

describe('cv store', () => {
  it('saves a PDF under a generated id and deletes it', () => {
    const dir = tmp()
    const { id } = saveCvFile(pdf, dir)
    expect(isCvId(id)).toBe(true)
    expect(fs.readFileSync(cvFilePath(id, dir))).toEqual(pdf)
    expect(deleteCvFile(id, dir)).toBe(true)
    expect(deleteCvFile(id, dir)).toBe(false)
  })
  it('refuses a non-PDF, an empty file and an oversized one', () => {
    const dir = tmp()
    expect(() => saveCvFile(Buffer.from('hello'), dir)).toThrow(/PDF/)
    expect(() => saveCvFile(Buffer.alloc(0), dir)).toThrow()
    expect(() => saveCvFile(Buffer.concat([pdf, Buffer.alloc(10 * 1024 * 1024)]), dir)).toThrow(/large/)
    expect(fs.readdirSync(dir)).toEqual([])
  })
  it('accepts only generated ids, so a request cannot name a path', () => {
    for (const bad of ['../x', '..%2fx', 'a/b', '', 'ABCDEF0123456789', '0123456789abcdef0']) {
      expect(isCvId(bad)).toBe(false)
      expect(() => cvFilePath(bad, '/tmp')).toThrow()
    }
  })
})
