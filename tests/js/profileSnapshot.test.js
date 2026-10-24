import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import fs from 'node:fs'
import { takeProfileSnapshot, profileChangedSince } from '../../src/utils/profileSnapshot.js'
import { restoreProfile, saveProfile } from '../../src/utils/storage.js'

const profile = () => ({
  basicProfile: { fullName: 'A', targetRoles: ['PM'], minSalaryEur: 1500 },
  questionnaire: { answers: [{ id: 1, answer: 'x' }] },
  meta: { lastStep: 2, updatedAt: '2026-01-01T00:00:00Z', onboardingComplete: true },
})

describe('profile snapshot', () => {
  it('is a deep copy that later edits cannot reach', () => {
    const p = profile()
    const snap = takeProfileSnapshot(p)
    p.basicProfile.targetRoles.push('CPO')
    p.questionnaire.answers[0].answer = 'changed'
    expect(snap).toEqual(profile())
  })

  it('sees an edit as a change, but not a step visit or a save stamp', () => {
    const snap = takeProfileSnapshot(profile())
    const visited = { ...profile(), meta: { ...profile().meta, lastStep: 4, updatedAt: '2026-02-02T00:00:00Z' } }
    expect(profileChangedSince(snap, visited)).toBe(false)
    const edited = profile()
    edited.basicProfile.minSalaryEur = 2000
    expect(profileChangedSince(snap, edited)).toBe(true)
    const answered = profile()
    answered.questionnaire.answers.push({ id: 2, answer: 'y' })
    expect(profileChangedSince(snap, answered)).toBe(true)
  })
})

describe('restoring a snapshot into localStorage', () => {
  const real = globalThis.localStorage
  let store
  beforeEach(() => {
    store = new Map()
    globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) }
  })
  afterEach(() => { globalThis.localStorage = real })

  it('writes the profile back exactly, undoing edits that autosaved', () => {
    const original = profile()
    saveProfile(original)
    const snap = takeProfileSnapshot(JSON.parse([...store.values()][0]))
    const edited = { ...snap, basicProfile: { ...snap.basicProfile, fullName: 'Someone Else', minSalaryEur: 9999 } }
    saveProfile(edited)
    expect(JSON.parse([...store.values()][0]).basicProfile.fullName).toBe('Someone Else')

    restoreProfile(snap)
    const back = JSON.parse([...store.values()][0])
    expect(back).toEqual(snap)                       // exact, including the old updatedAt
    expect(back.basicProfile.minSalaryEur).toBe(1500)
  })
})

describe('Edit Profile footer', () => {
  const src = fs.readFileSync('src/components/onboarding/OnboardingWizard.jsx', 'utf8')

  it('has Cancel next to Done, and Done still just exits', () => {
    expect(src).toMatch(/onClick=\{cancelEdit\}/)
    expect(src).toMatch(/onClick=\{\(\) => onComplete\?\.\(\)\}[\s\S]{0,40}Done/)
  })

  it('takes the snapshot only when editing, once, when the wizard mounts', () => {
    expect(src).toMatch(/useState\(\(\) => \(mode === 'edit' \? takeProfileSnapshot\(profile\) : null\)\)/)
  })
})
