import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BackupError, backupProfileForImport, listImportBackups } from '../../scripts/profile-backup.js'
import { writeProfileFile } from '../../scripts/save-profile.js'

const CANARY = 'CANARY-NAME-9931'
let root
let tick
const now = () => new Date(2026, 10, 9, 10, 0, tick++)
const profile = (extra = {}) => ({ basicProfile: { fullName: CANARY }, cvLibrary: [], _editedFields: { skills: true }, ...extra })
const mode = (p) => fs.statSync(p).mode & 0o777

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'pbackup-'))
  tick = 0
})

describe('backupProfileForImport', () => {
  it('writes the profile as given (edited-field marks included), private, read back and verified', () => {
    const res = backupProfileForImport(root, profile(), { now })
    const file = path.join(root, res.path)
    expect(JSON.parse(fs.readFileSync(file, 'utf-8'))).toEqual(profile())
    expect(mode(file)).toBe(0o600)
    expect(mode(path.dirname(file))).toBe(0o700)
    expect(res.sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(path.basename(path.dirname(file))).toMatch(/^profile-import-\d{8}-\d{6}$/)
  })

  it('two backups in the same second get distinct folders', () => {
    const fixed = () => new Date(2026, 10, 9, 10, 0, 0)
    const a = backupProfileForImport(root, profile(), { now: fixed })
    const b = backupProfileForImport(root, profile({ x: 1 }), { now: fixed })
    expect(a.path).not.toBe(b.path)
    expect(JSON.parse(fs.readFileSync(path.join(root, a.path), 'utf-8')).x).toBeUndefined()
  })

  it('keeps the newest 10 and touches no other folder under data/backups', () => {
    const other = path.join(root, 'data/backups/applications-20260101-000000')
    fs.mkdirSync(other, { recursive: true })
    fs.writeFileSync(path.join(other, 'applications.json'), '{}')
    const lookalike = path.join(root, 'data/backups/profile-import-notes')
    fs.mkdirSync(lookalike)
    const paths = Array.from({ length: 13 }, () => backupProfileForImport(root, profile(), { now }).path)
    const left = listImportBackups(path.join(root, 'data/backups'))
    expect(left).toHaveLength(10)
    expect(left.map((n) => path.join('data/backups', n, 'candidate-profile.json'))).toEqual(paths.slice(3))
    expect(fs.existsSync(other)).toBe(true)
    expect(fs.existsSync(lookalike)).toBe(true)
  })

  it('refuses a non-object profile without writing anything', () => {
    for (const bad of [null, 'x', [], 5, undefined]) expect(() => backupProfileForImport(root, bad, { now })).toThrow(BackupError)
    expect(fs.existsSync(path.join(root, 'data/backups'))).toBe(false)
  })

  it('a write failure is a fixed code that carries nothing from the profile', () => {
    fs.mkdirSync(path.join(root, 'data'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/backups'), 'a file where the folder should be')
    let error
    try { backupProfileForImport(root, profile(), { now }) } catch (e) { error = e }
    expect(error).toBeInstanceOf(BackupError)
    expect(error.code).toBe('backup_failed')
    expect(JSON.stringify([error.message, error.code])).not.toContain(CANARY)
  })
})

describe('writeProfileFile is atomic', () => {
  it('replaces the file whole and keeps its mode; no temp file is left', () => {
    const file = path.join(root, 'data/profile/candidate-profile.json')
    writeProfileFile({ a: 1 }, file)
    expect(mode(file)).toBe(0o600)
    writeProfileFile({ a: 2 }, file)
    expect(JSON.parse(fs.readFileSync(file, 'utf-8'))).toEqual({ a: 2 })
    expect(fs.readdirSync(path.dirname(file))).toEqual(['candidate-profile.json'])
  })

  it('a failure while writing leaves the previous file intact', () => {
    const file = path.join(root, 'data/profile/candidate-profile.json')
    writeProfileFile({ keep: 'me' }, file)
    const circular = {}
    circular.self = circular
    expect(() => writeProfileFile(circular, file)).toThrow()
    expect(JSON.parse(fs.readFileSync(file, 'utf-8'))).toEqual({ keep: 'me' })
    const spy = vi.spyOn(fs, 'renameSync').mockImplementation(() => { throw new Error('disk') })
    expect(() => writeProfileFile({ new: 1 }, file)).toThrow('disk')
    spy.mockRestore()
    expect(JSON.parse(fs.readFileSync(file, 'utf-8'))).toEqual({ keep: 'me' })
    expect(fs.readdirSync(path.dirname(file))).toEqual(['candidate-profile.json'])
  })
})
