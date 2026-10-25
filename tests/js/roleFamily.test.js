import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import roleFamilies from '../../src/data/roleFamilies.json'
import { ROLE_FAMILY_IDS, ROLE_FAMILY_LABELS, normalizeRoleFamily } from '../../src/utils/roleFamily.js'
import { generateCandidateIntelligence } from '../../src/modules/intelligence/candidateIntelligenceEngine.js'
import { getDefaultProfile, loadProfile, saveProfile, STORAGE_KEY } from '../../src/utils/storage.js'
import { buildExportProfile } from '../../src/utils/exportJson.js'
import { saveProfileToDisk } from '../../scripts/save-profile.js'
import sampleProfile from '../../fixtures/candidate-profile.sample.json'

const withFamily = (roleFamily) => ({ ...sampleProfile, basicProfile: { ...sampleProfile.basicProfile, roleFamily } })

describe('role family ids', () => {
  it('are the families scoring knows, each with a label', () => {
    expect(ROLE_FAMILY_IDS).toEqual(Object.keys(roleFamilies))
    expect(ROLE_FAMILY_IDS).toEqual(['product', 'engineering', 'design', 'qa', 'data', 'delivery', 'marketing', 'sales'])
    for (const id of ROLE_FAMILY_IDS) expect(ROLE_FAMILY_LABELS[id]).toBeTruthy()
  })

  it('normalize to a known id or nothing, never a default', () => {
    expect(normalizeRoleFamily('engineering')).toBe('engineering')
    for (const bad of [undefined, null, '', 'astronaut', 'Product', 3]) expect(normalizeRoleFamily(bad)).toBe('')
  })
})

describe('profile write-through', () => {
  const realLocalStorage = globalThis.localStorage

  beforeEach(() => {
    const store = new Map()
    globalThis.localStorage = {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    }
  })

  afterEach(() => {
    globalThis.localStorage = realLocalStorage
    vi.restoreAllMocks()
  })

  it('starts unset', () => {
    expect(getDefaultProfile().basicProfile.roleFamily).toBe('')
    expect(loadProfile().basicProfile.roleFamily).toBe('')
  })

  it('reads a profile saved before the field existed as unset', () => {
    const { roleFamily, ...oldBasic } = getDefaultProfile().basicProfile
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...getDefaultProfile(), basicProfile: oldBasic }))
    expect(roleFamily).toBe('')
    expect(loadProfile().basicProfile.roleFamily).toBe('')
  })

  it('survives save and reload, and an unknown id is dropped on load', () => {
    const profile = loadProfile()
    saveProfile({ ...profile, basicProfile: { ...profile.basicProfile, roleFamily: 'product' } })
    expect(loadProfile().basicProfile.roleFamily).toBe('product')
    saveProfile({ ...profile, basicProfile: { ...profile.basicProfile, roleFamily: 'astronaut' } })
    expect(loadProfile().basicProfile.roleFamily).toBe('')
  })

  it('reaches the disk mirror Python reads', () => {
    const written = []
    vi.spyOn(fs, 'mkdirSync').mockImplementation(() => {})
    vi.spyOn(fs, 'writeFileSync').mockImplementation((path, data) => written.push([String(path), data]))
    saveProfileToDisk(buildExportProfile(withFamily('product')))
    expect(written).toHaveLength(1)
    expect(written[0][0]).toMatch(/data\/profile\/candidate-profile\.json$/)
    expect(JSON.parse(written[0][1]).basicProfile.roleFamily).toBe('product')
  })
})

describe('intelligence', () => {
  it('carries the chosen family, which scoring reads', () => {
    expect(generateCandidateIntelligence(withFamily('product')).roleFamily).toBe('product')
    expect(generateCandidateIntelligence(withFamily('data')).roleFamily).toBe('data')
  })

  it('is null without one, so nothing is assumed', () => {
    expect(generateCandidateIntelligence(withFamily('')).roleFamily).toBeNull()
    expect(generateCandidateIntelligence(withFamily('astronaut')).roleFamily).toBeNull()
    expect(generateCandidateIntelligence(sampleProfile).roleFamily).toBeNull()
  })
})
