import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { copyToNewFile, replaceFileAtomic } from '../../scripts/atomic-file.js'
import { writeFileAtomic } from '../../scripts/application-store.js'
import { importBackupZip } from '../../scripts/backup-handler.js'
import { saveCvFile } from '../../scripts/cv-store.js'
import { resetProfileOnDisk } from '../../scripts/profile-reset.js'
import { PROFILE_PATH, saveProfileToDisk } from '../../scripts/save-profile.js'
import { writeCoverLetter, writeInterviewPrep, writeSkillGap } from '../../scripts/run-ai.js'
import { writeContactsFile } from '../../scripts/run-outreach.js'
import { INTELLIGENCE_PATH, saveIntelligenceToDisk, writeIntelligenceFile } from '../../scripts/save-intelligence.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')
const SCRIPT = fileURLToPath(new URL('../../scripts/tighten-data-permissions.sh', import.meta.url))

let root

const abs = (rel) => path.join(root, rel)
const modeOf = (rel) => fs.statSync(abs(rel)).mode & 0o777
const put = (rel, content, mode = 0o644) => {
  fs.mkdirSync(path.dirname(abs(rel)), { recursive: true })
  fs.writeFileSync(abs(rel), content)
  fs.chmodSync(abs(rel), mode)
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'data-perms-'))
})

afterEach(() => {
  vi.restoreAllMocks()
  fs.rmSync(root, { recursive: true, force: true })
})

describe('replaceFileAtomic with a mode', () => {
  it('gives a new file the mode before any byte is written', () => {
    let during
    const real = fs.writeFileSync
    vi.spyOn(fs, 'writeFileSync').mockImplementationOnce((fd, data) => {
      during = fs.fstatSync(fd).mode & 0o777
      return real(fd, data)
    })
    replaceFileAtomic(abs('new.json'), 'x', { mode: 0o600 })
    expect(during).toBe(0o600)
    expect(modeOf('new.json')).toBe(0o600)
  })

  it('keeps the mode of an existing target, wider or narrower', () => {
    put('open.json', 'old', 0o644)
    put('shut.json', 'old', 0o400)
    replaceFileAtomic(abs('open.json'), 'new', { mode: 0o600 })
    replaceFileAtomic(abs('shut.json'), 'new', { mode: 0o600 })
    expect(modeOf('open.json')).toBe(0o644)
    expect(modeOf('shut.json')).toBe(0o400)
    expect(fs.readFileSync(abs('open.json'), 'utf-8')).toBe('new')
  })

  it('without a mode, a new file still gets the process default', () => {
    replaceFileAtomic(abs('default.json'), 'x')
    fs.writeFileSync(abs('plain.json'), 'x')
    expect(modeOf('default.json')).toBe(modeOf('plain.json'))
  })

  it.each([
    ['write', 'writeFileSync'],
    ['fsync', 'fsyncSync'],
    ['rename', 'renameSync'],
  ])('a failed %s leaves no target and no temp file', (_label, method) => {
    vi.spyOn(fs, method).mockImplementationOnce(() => { throw new Error('disk full') })
    expect(() => replaceFileAtomic(abs('new.json'), 'x', { mode: 0o600 })).toThrow('disk full')
    expect(fs.readdirSync(root)).toEqual([])
  })

  it('a failed write leaves an existing target and its mode as they were', () => {
    put('kept.json', 'old', 0o640)
    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    expect(() => replaceFileAtomic(abs('kept.json'), 'new', { mode: 0o600 })).toThrow('disk full')
    expect(fs.readFileSync(abs('kept.json'), 'utf-8')).toBe('old')
    expect(modeOf('kept.json')).toBe(0o640)
    expect(fs.readdirSync(root)).toEqual(['kept.json'])
  })
})

describe('copyToNewFile', () => {
  it('does not carry the source mode over', () => {
    put('src.pdf', 'body', 0o644)
    copyToNewFile(abs('src.pdf'), abs('dest.pdf'), 0o600)
    expect(modeOf('dest.pdf')).toBe(0o600)
    expect(fs.readFileSync(abs('dest.pdf'), 'utf-8')).toBe('body')
  })

  it('refuses an existing destination with EEXIST and leaves it alone', () => {
    put('src.pdf', 'new')
    put('dest.pdf', 'old', 0o644)
    expect(() => copyToNewFile(abs('src.pdf'), abs('dest.pdf'), 0o600)).toThrow(expect.objectContaining({ code: 'EEXIST' }))
    expect(fs.readFileSync(abs('dest.pdf'), 'utf-8')).toBe('old')
    expect(modeOf('dest.pdf')).toBe(0o644)
  })

  it('removes the destination when the write fails', () => {
    put('src.pdf', 'new')
    vi.spyOn(fs, 'writeFileSync').mockImplementationOnce(() => { throw new Error('disk full') })
    expect(() => copyToNewFile(abs('src.pdf'), abs('dest.pdf'), 0o600)).toThrow('disk full')
    expect(fs.existsSync(abs('dest.pdf'))).toBe(false)
  })
})

describe('application store files', () => {
  it('a new file is 600 in new 700 folders', () => {
    fs.mkdirSync(abs('data'))
    writeFileAtomic(abs('data/applications/files/app-1/cv.pdf'), 'x')
    expect(modeOf('data/applications/files/app-1/cv.pdf')).toBe(0o600)
    for (const dir of ['data/applications', 'data/applications/files', 'data/applications/files/app-1']) expect(modeOf(dir)).toBe(0o700)
  })

  it('a rewrite no longer resets a tightened file, and an old folder and file keep their modes', () => {
    put('data/applications/applications.json', 'old', 0o600)
    put('data/applications/settings.json', 'old', 0o644)
    fs.chmodSync(abs('data/applications'), 0o755)
    writeFileAtomic(abs('data/applications/applications.json'), 'new')
    writeFileAtomic(abs('data/applications/settings.json'), 'new')
    expect(modeOf('data/applications/applications.json')).toBe(0o600)
    expect(modeOf('data/applications/settings.json')).toBe(0o644)
    expect(modeOf('data/applications')).toBe(0o755)
  })
})

describe('uploaded CVs', () => {
  it('are 600 in a new 700 folder', () => {
    const dir = abs('cvs')
    const { id } = saveCvFile(Buffer.from('%PDF-1.4\nbody'), dir)
    expect(modeOf(`cvs/${id}.pdf`)).toBe(0o600)
    expect(modeOf('cvs')).toBe(0o700)
  })
})

describe('profile mirror', () => {
  it('asks for 600 / 700 on the file and folder it creates', () => {
    // The path is fixed under the repo, so the writes are intercepted and never reach the real file.
    const mkdir = vi.spyOn(fs, 'mkdirSync').mockImplementation(() => {})
    const write = vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
    saveProfileToDisk({ basicProfile: {} })
    expect(mkdir).toHaveBeenCalledWith(path.dirname(PROFILE_PATH), { recursive: true, mode: 0o700 })
    expect(write).toHaveBeenCalledWith(PROFILE_PATH, expect.any(String), { encoding: 'utf-8', mode: 0o600 })
  })
})

describe('saved AI answers', () => {
  const writers = [
    ['interview prep', () => writeInterviewPrep('job-1', { answer: 'x' }), 'interviews/job-1/interview_prep.json'],
    ['cover letter', () => writeCoverLetter('job-1', { short: 'x' }), 'resumes/job-1/ai_cover_letter.md'],
    ['skill gap', () => writeSkillGap({ answer: 'x' }), 'analytics/skill_gap.json'],
  ]

  beforeEach(() => vi.stubEnv('CAREER_OS_AI_OUTPUT_DIR', root))
  afterEach(() => vi.unstubAllEnvs())

  it.each(writers)('a new %s is 600 in new 700 folders', (_label, write, rel) => {
    expect(write()).toBe(abs(rel))
    expect(modeOf(rel)).toBe(0o600)
    expect(modeOf(path.dirname(rel))).toBe(0o700)
  })

  it.each(writers)('rewriting a %s keeps the file and folder modes', (_label, write, rel) => {
    put(rel, 'old', 0o640)
    fs.chmodSync(abs(path.dirname(rel)), 0o755)
    write()
    expect(modeOf(rel)).toBe(0o640)
    expect(modeOf(path.dirname(rel))).toBe(0o755)
    expect(fs.readFileSync(abs(rel), 'utf-8')).not.toBe('old')
  })
})

describe('outreach contacts', () => {
  it('are 600 in new 700 folders', () => {
    const file = writeContactsFile('job-1', { contacts: [] }, abs('outreach'))
    expect(file).toBe(abs('outreach/job-1/contacts.json'))
    expect(modeOf('outreach/job-1/contacts.json')).toBe(0o600)
    expect(modeOf('outreach/job-1')).toBe(0o700)
    expect(modeOf('outreach')).toBe(0o700)
  })

  it('keep the modes of an existing file and folder', () => {
    put('outreach/job-1/contacts.json', 'old', 0o644)
    fs.chmodSync(abs('outreach/job-1'), 0o755)
    writeContactsFile('job-1', { contacts: ['x'] }, abs('outreach'))
    expect(modeOf('outreach/job-1/contacts.json')).toBe(0o644)
    expect(modeOf('outreach/job-1')).toBe(0o755)
    expect(JSON.parse(fs.readFileSync(abs('outreach/job-1/contacts.json'), 'utf-8'))).toEqual({ contacts: ['x'] })
  })
})

describe('candidate intelligence', () => {
  it('is 600 in a new 700 folder', () => {
    writeIntelligenceFile({ meta: {} }, abs('intelligence/candidate-intelligence.json'))
    expect(modeOf('intelligence/candidate-intelligence.json')).toBe(0o600)
    expect(modeOf('intelligence')).toBe(0o700)
  })

  it('keeps the modes of an existing file and folder', () => {
    put('intelligence/candidate-intelligence.json', 'old', 0o640)
    fs.chmodSync(abs('intelligence'), 0o755)
    writeIntelligenceFile({ meta: {} }, abs('intelligence/candidate-intelligence.json'))
    expect(modeOf('intelligence/candidate-intelligence.json')).toBe(0o640)
    expect(modeOf('intelligence')).toBe(0o755)
  })

  it('the route saves through the same modes', () => {
    // The path is fixed under the repo, so the writes are intercepted and never reach the real file.
    const mkdir = vi.spyOn(fs, 'mkdirSync').mockImplementation(() => {})
    const write = vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
    saveIntelligenceToDisk({ meta: {} })
    expect(mkdir).toHaveBeenCalledWith(path.dirname(INTELLIGENCE_PATH), { recursive: true, mode: 0o700 })
    expect(write).toHaveBeenCalledWith(INTELLIGENCE_PATH, expect.any(String), { encoding: 'utf-8', mode: 0o600 })
  })
})

describe('backup restore', () => {
  const zipOf = (entries) => {
    const zip = new AdmZip()
    for (const [name, data] of Object.entries(entries)) zip.addFile(name, Buffer.from(data))
    return zip.toBuffer()
  }

  it.each([
    'data/profile/cvs/a.pdf', 'data/config/sources.json', 'data/ai/findings/job/a.json', 'data/ai/usage-ledger.jsonl', 'data/backups/x/a.json',
    'data/profile.bak-1/a.json', 'data/intelligence/a.json', 'data/outreach/job-1/contacts.json', 'data/interviews/job-1/a.json',
    'data/analytics/a.json', 'data/resumes/job-1/a.pdf',
  ])(
    'restores a new %s as 600 in new 700 folders', async (name) => {
      await importBackupZip(root, zipOf({ [name]: 'x' }))
      expect(modeOf(name)).toBe(0o600)
      expect(modeOf(path.dirname(name))).toBe(0o700)
    },
  )

  it('keeps the mode of an existing private file and leaves other folders at the default', async () => {
    put('data/profile/candidate-profile.json', 'old', 0o644)
    put('data/jobs/plain.json', 'x')
    fs.chmodSync(abs('data/jobs/plain.json'), 0o666 & ~process.umask())
    await importBackupZip(root, zipOf({ 'data/profile/candidate-profile.json': 'new', 'data/jobs/new.json': 'x' }))
    expect(modeOf('data/profile/candidate-profile.json')).toBe(0o644)
    expect(modeOf('data/jobs/new.json')).toBe(modeOf('data/jobs/plain.json'))
  })
})

describe('profile reset backup', () => {
  const NOW = new Date(2026, 10, 1, 9, 5, 7)

  it('holds only 600 files and 700 folders, whatever the source modes were', () => {
    put('profile/candidate-profile.json', '{}', 0o644)
    put('profile/cvs/0123456789abcdef.pdf', '%PDF', 0o644)
    fs.chmodSync(abs('profile/cvs'), 0o755)
    const { ok, backup } = resetProfileOnDisk({ dataDir: root, now: NOW })
    expect(ok).toBe(true)
    expect(modeOf(backup)).toBe(0o700)
    expect(modeOf(`${backup}/profile`)).toBe(0o700)
    expect(modeOf(`${backup}/profile/cvs`)).toBe(0o700)
    expect(modeOf(`${backup}/profile/candidate-profile.json`)).toBe(0o600)
    expect(modeOf(`${backup}/profile/cvs/0123456789abcdef.pdf`)).toBe(0o600)
  })

  it('a failed tightening counts as a failed backup, so the originals stay', () => {
    put('profile/candidate-profile.json', '{}', 0o644)
    const failing = { ...fs, chmodSync: () => { throw new Error('nope') } }
    expect(resetProfileOnDisk({ dataDir: root, now: NOW, fsImpl: failing })).toEqual({ ok: false, code: 'backup_failed' })
    expect(fs.existsSync(abs('profile/candidate-profile.json'))).toBe(true)
    expect(fs.readdirSync(root)).toEqual(['profile'])
  })
})

describe('tighten-data-permissions.sh', () => {
  const run = (...args) => spawnSync('sh', [SCRIPT, '--data-dir', abs('data'), ...args], { encoding: 'utf-8' })

  const OPEN_FILES = [
    'data/profile/candidate-profile.json',
    'data/profile/cvs/name with space.pdf',
    'data/applications/applications.json',
    'data/applications/files/app-1/cv.pdf',
    'data/ai/findings/job/a.json',
    'data/ai/settings.json',
    'data/ai/pricing-overrides.json',
    'data/ai/usage-ledger.jsonl',
    'data/ai/.ledger.lock',
    'data/config/ai-settings.json',
    'data/backups/x/a.json',
    'data/profile.bak-1/a.json',
    'data/intelligence/candidate-intelligence.json',
    'data/outreach/job-1/contacts.json',
    'data/interviews/job-1/interview_prep.json',
    'data/analytics/skill_gap.json',
    'data/resumes/job-1/cv.pdf',
  ]
  const OPEN_DIRS = [
    'data/profile', 'data/profile/cvs', 'data/applications/files/app-1', 'data/ai', 'data/config', 'data/backups/x', 'data/profile.bak-1',
    'data/intelligence', 'data/outreach', 'data/outreach/job-1', 'data/interviews/job-1', 'data/analytics', 'data/resumes/job-1',
  ]

  beforeEach(() => {
    for (const rel of OPEN_FILES) put(rel, 'x', 0o644)
    for (const rel of OPEN_DIRS) fs.chmodSync(abs(rel), 0o755)
    put('data/jobs/scored_jobs.json', 'x', 0o644)
    put('data/cache/engine.json', 'x', 0o644)
    put('data/config/read-only.json', 'x', 0o400)
    put('outside.json', 'x', 0o644)
    fs.symlinkSync(abs('outside.json'), abs('data/profile/link.json'))
  })

  it('a dry run lists and changes nothing', () => {
    const result = run()
    expect(result.status).toBe(0)
    expect(result.stdout).toContain('name with space.pdf')
    expect(result.stdout).toContain('Nothing was changed')
    for (const rel of OPEN_FILES) expect(modeOf(rel)).toBe(0o644)
    for (const rel of OPEN_DIRS) expect(modeOf(rel)).toBe(0o755)
  })

  it('--apply tightens the listed folders only, and a second run finds nothing', () => {
    const result = run('--apply')
    expect(result.status).toBe(0)
    for (const rel of OPEN_FILES) expect(modeOf(rel)).toBe(0o600)
    for (const rel of OPEN_DIRS) expect(modeOf(rel)).toBe(0o700)
    expect(modeOf('data/config/read-only.json')).toBe(0o400) // never widened
    expect(modeOf('data/jobs/scored_jobs.json')).toBe(0o644)
    expect(modeOf('data/cache/engine.json')).toBe(0o644)
    expect(modeOf('data/jobs')).not.toBe(0o700)
    expect(modeOf('data/cache')).not.toBe(0o700)
    expect(modeOf('outside.json')).toBe(0o644) // a symlink is not followed
    expect(run().stdout).toContain('Dry run: 0 files and 0 directories')
    expect(run('--apply').stdout).toContain('Changed 0 files and 0 directories')
  })

  it('skips a covered folder that is a symlink, and leaves what it points at alone', () => {
    fs.rmSync(abs('data/outreach'), { recursive: true })
    put('elsewhere/contacts.json', 'x', 0o644)
    fs.chmodSync(abs('elsewhere'), 0o755)
    fs.symlinkSync(abs('elsewhere'), abs('data/outreach'))
    const result = run('--apply')
    expect(result.status).toBe(0)
    expect(result.stderr).toContain('Skipped, a symlink')
    expect(modeOf('elsewhere/contacts.json')).toBe(0o644)
    expect(modeOf('elsewhere')).toBe(0o755)
  })

  it('works when a folder is missing, and refuses an unknown argument', () => {
    fs.rmSync(abs('data/profile.bak-1'), { recursive: true })
    fs.rmSync(abs('data/backups'), { recursive: true })
    expect(run('--apply').status).toBe(0)
    expect(run('--force').status).toBe(2)
  })
})
