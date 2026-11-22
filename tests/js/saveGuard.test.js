// The save guard: a save that would empty or cut the owner's filled-in settings is refused (the overwrite of 2026-11-21 02:12);
// a normal edit and a first save pass. Synthetic data only.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sendSaveFailure } from '../../scripts/api-handler.js'
import { BackupError } from '../../scripts/auto-backup.js'
import { GUARD_LOSS_LIMIT, SaveRefused, assertSafeToReplace, findLosses } from '../../scripts/save-guard.js'
import { writeProfileFile } from '../../scripts/save-profile.js'
import { writeIntelligenceFile } from '../../scripts/save-intelligence.js'

const ROLES = ['Product Manager', 'Senior Product Manager', 'Lead Product Manager', 'Technical Product Manager', 'Product Owner',
  'Group Product Manager', 'Platform Product Manager', 'Growth Product Manager', 'Product Lead']

const serverProfile = () => ({
  basicProfile: {
    fullName: 'Test Person', targetRoles: [...ROLES], allowedLocations: ['RS', 'DE', 'AT', 'NL', 'REMOTE'], preferredLocations: ['Nis'],
    languages: ['Serbian (native)', 'English (advanced)'], remotePreference: 'remote', roleFamily: 'product', minSalaryEur: 3000,
    desiredSalaryMinEur: 4000, desiredSalaryMaxEur: 6000, salaryExpectation: '4000-6000',
    workAuthorization: { holds: [{ jurisdiction: 'RS', basis: 'citizen' }], openToSponsorship: false },
  },
  questionnaire: { answers: [1, 2, 3, 4, 5].map((n) => ({ id: `q${n}`, question: 'q', answer: 'a' })) },
  repositories: { githubLinks: ['https://github.com/example'] },
  cvLibrary: [{ id: 'cv-1' }, { id: 'cv-2' }],
  resume: { parsedData: { skills: ['SQL'] } },
  meta: { updatedAt: '2026-11-19T10:00:00.000Z' },
})

// What a browser with an empty profile sends after the CV was pasted and the init setup was run: one role, no preferences, no answers.
const freshBrowserProfile = () => ({
  basicProfile: {
    fullName: 'Test Person', targetRoles: ['Product manager'], allowedLocations: [], preferredLocations: [], languages: [], remotePreference: '',
    roleFamily: '', minSalaryEur: null, desiredSalaryMinEur: null, desiredSalaryMaxEur: null, salaryExpectation: '',
    workAuthorization: { holds: [], openToSponsorship: false },
  },
  questionnaire: { answers: [] },
  repositories: { githubLinks: [] },
  cvLibrary: [{ id: 'cv-new' }],
  resume: { parsedData: { skills: ['SQL', 'Jira'], summary: 'pasted CV text' } },
  meta: {},
})

const serverIntelligence = () => ({
  languages: ['Serbian (native)', 'English (advanced)'],
  roleFamily: 'product',
  roleStrategy: { primaryTargetRoles: [...ROLES], secondaryTargetRoles: ROLES.slice(0, 6), stretchRoles: ['Head of Product'], avoidRoles: [], searchRoleVariants: ROLES.slice(0, 5) },
  searchStrategy: { jobSpySearchTerms: ROLES.slice(0, 6), linkedinSearchQueries: ROLES.slice(0, 4), recommendedSearchQueries: ROLES.slice(0, 3), locationFilters: ['Serbia', 'Remote', 'EU'] },
  jobFitPreferences: {
    allowedLocations: ['RS', 'DE', 'AT'], preferredLocations: ['Nis'], preferredIndustries: ['SaaS', 'Fintech'], avoidedIndustries: [], preferredCompanyTypes: ['Product company'],
    workToAvoid: [], remotePreference: 'remote', salaryExpectation: '4000-6000', minSalaryEur: 3000, desiredSalaryEur: { min: 4000, max: 6000 },
    workAuthorization: { holds: [{ jurisdiction: 'RS', basis: 'citizen' }], openToSponsorship: false },
  },
  meta: { generatedAt: '2026-11-13T22:51:47.002Z' },
})

const freshBrowserIntelligence = () => ({
  languages: [], roleFamily: null,
  roleStrategy: { primaryTargetRoles: ['Product manager'], secondaryTargetRoles: [], stretchRoles: [], avoidRoles: [], searchRoleVariants: ['Product manager'] },
  searchStrategy: { jobSpySearchTerms: ['Product manager'], linkedinSearchQueries: [], recommendedSearchQueries: [], locationFilters: [] },
  jobFitPreferences: { allowedLocations: [], preferredLocations: [], preferredIndustries: [], avoidedIndustries: [], preferredCompanyTypes: [], workToAvoid: [],
    remotePreference: '', salaryExpectation: '', minSalaryEur: null, desiredSalaryEur: { min: null, max: null }, workAuthorization: { holds: [], openToSponsorship: false } },
  meta: { generatedAt: '2026-11-21T01:13:13.663Z' },
})

describe('the overwrite of 2026-11-21 is refused', () => {
  it('a fresh browser profile would empty many filled-in settings', () => {
    const lost = findLosses('profile', serverProfile(), freshBrowserProfile())
    expect(lost.length).toBeGreaterThan(GUARD_LOSS_LIMIT)
    expect(lost).toEqual(expect.arrayContaining(['basicProfile.targetRoles', 'basicProfile.allowedLocations', 'basicProfile.languages', 'questionnaire.answers']))
    expect(() => assertSafeToReplace('profile', serverProfile(), freshBrowserProfile())).toThrow(SaveRefused)
  })

  it('a fresh browser intelligence is refused too', () => {
    expect(findLosses('intelligence', serverIntelligence(), freshBrowserIntelligence()).length).toBeGreaterThan(GUARD_LOSS_LIMIT)
    expect(() => assertSafeToReplace('intelligence', serverIntelligence(), freshBrowserIntelligence())).toThrow(SaveRefused)
  })

  it('the refusal names fields only, never a value, and logs the same', () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    let error
    try { assertSafeToReplace('profile', serverProfile(), freshBrowserProfile()) } catch (e) { error = e }
    const text = `${error.message} ${log.mock.calls.flat().join(' ')}`
    expect(error.code).toBe('would_lose_data')
    expect(error.status).toBe(409)
    expect(text).toContain('basicProfile.targetRoles')
    for (const secret of ['Test Person', 'Serbian', 'SQL', 'github.com', '4000']) expect(text).not.toContain(secret)
    log.mockRestore()
  })
})

describe('a normal save passes', () => {
  it('one edited field', () => {
    const next = serverProfile()
    next.basicProfile.remotePreference = 'hybrid'
    expect(findLosses('profile', serverProfile(), next)).toEqual([])
  })

  it('one role removed from nine, and roles added', () => {
    const next = serverProfile()
    next.basicProfile.targetRoles = [...ROLES.slice(1), 'Chief Product Officer']
    expect(findLosses('profile', serverProfile(), next)).toEqual([])
  })

  it('one or two fields cleared on purpose (below the limit)', () => {
    const one = serverProfile()
    one.basicProfile.salaryExpectation = ''
    const two = serverIntelligence()
    two.languages = []
    two.jobFitPreferences.preferredIndustries = []
    expect(() => assertSafeToReplace('profile', serverProfile(), one)).not.toThrow()
    expect(() => assertSafeToReplace('intelligence', serverIntelligence(), two)).not.toThrow()
  })

  it('exactly the limit is refused', () => {
    const next = serverProfile()
    next.basicProfile.languages = []
    next.basicProfile.salaryExpectation = ''
    next.basicProfile.roleFamily = ''
    expect(findLosses('profile', serverProfile(), next)).toHaveLength(GUARD_LOSS_LIMIT)
    expect(() => assertSafeToReplace('profile', serverProfile(), next)).toThrow(SaveRefused)
  })

  it('a first save, a server file with nothing filled in, and an unreadable server file', () => {
    expect(findLosses('profile', null, freshBrowserProfile())).toEqual([])
    expect(findLosses('profile', { basicProfile: {} }, freshBrowserProfile())).toEqual([])
    expect(findLosses('intelligence', {}, freshBrowserIntelligence())).toEqual([])
  })
})

describe('what the two save routes answer', () => {
  const answer = (error) => {
    const res = { writableEnded: false, headers: {}, setHeader(k, v) { this.headers[k] = v }, end(body) { this.body = JSON.parse(body); this.writableEnded = true } }
    sendSaveFailure(res, error)
    return res
  }

  it('a refused save is 409 with the code and the field names', () => {
    const res = answer(new SaveRefused('profile', ['basicProfile.targetRoles', 'basicProfile.languages', 'questionnaire.answers']))
    expect(res.statusCode).toBe(409)
    expect(res.body.code).toBe('would_lose_data')
    expect(res.body.fields).toEqual(['basicProfile.targetRoles', 'basicProfile.languages', 'questionnaire.answers'])
    expect(res.body.error).toContain('Nothing was changed')
  })

  it('a failed backup is 500, a bad payload stays 400', () => {
    expect(answer(new BackupError('scored_jobs.json')).statusCode).toBe(500)
    const bad = answer(new Error('Invalid profile payload'))
    expect(bad.statusCode).toBe(400)
    expect(bad.body).toEqual({ error: 'Invalid profile payload' })
  })
})

describe('the writers (temp data folder)', () => {
  let tmp
  beforeEach(() => { tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'save-guard-')) })
  afterEach(() => { fs.rmSync(tmp, { recursive: true, force: true }) })
  const dataRoot = () => path.join(tmp, 'data')
  const file = (...parts) => path.join(dataRoot(), ...parts)
  const seed = (rel, doc) => { fs.mkdirSync(path.dirname(file(rel)), { recursive: true }); fs.writeFileSync(file(rel), JSON.stringify(doc, null, 2)) }

  it('a refused profile save changes nothing and makes no backup', () => {
    seed('profile/candidate-profile.json', serverProfile())
    const before = fs.readFileSync(file('profile/candidate-profile.json'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => writeProfileFile(freshBrowserProfile(), file('profile/candidate-profile.json'), { dataRoot: dataRoot() })).toThrow(SaveRefused)
    expect(fs.readFileSync(file('profile/candidate-profile.json')).equals(before)).toBe(true)
    expect(fs.existsSync(file('backups'))).toBe(false)
    vi.restoreAllMocks()
  })

  it('a refused intelligence save changes nothing', () => {
    seed('intelligence/candidate-intelligence.json', serverIntelligence())
    const before = fs.readFileSync(file('intelligence/candidate-intelligence.json'))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => writeIntelligenceFile(freshBrowserIntelligence(), file('intelligence/candidate-intelligence.json'), { dataRoot: dataRoot() })).toThrow(SaveRefused)
    expect(fs.readFileSync(file('intelligence/candidate-intelligence.json')).equals(before)).toBe(true)
    vi.restoreAllMocks()
  })

  it('an accepted edit is written after the old version was backed up', () => {
    seed('profile/candidate-profile.json', serverProfile())
    const old = fs.readFileSync(file('profile/candidate-profile.json'))
    const next = serverProfile()
    next.basicProfile.remotePreference = 'hybrid'
    writeProfileFile(next, file('profile/candidate-profile.json'), { dataRoot: dataRoot() })
    expect(JSON.parse(fs.readFileSync(file('profile/candidate-profile.json'), 'utf8')).basicProfile.remotePreference).toBe('hybrid')
    const dir = file('backups/auto/candidate-profile.json')
    const versions = fs.readdirSync(dir)
    expect(versions).toHaveLength(1)
    expect(fs.readFileSync(path.join(dir, versions[0])).equals(old)).toBe(true)
  })

  it('a first-ever save on an empty server is written, with no backup to make', () => {
    writeProfileFile(freshBrowserProfile(), file('profile/candidate-profile.json'), { dataRoot: dataRoot() })
    writeIntelligenceFile(freshBrowserIntelligence(), file('intelligence/candidate-intelligence.json'), { dataRoot: dataRoot() })
    expect(fs.existsSync(file('profile/candidate-profile.json'))).toBe(true)
    expect(fs.existsSync(file('intelligence/candidate-intelligence.json'))).toBe(true)
    expect(fs.existsSync(file('backups'))).toBe(false)
  })
})
