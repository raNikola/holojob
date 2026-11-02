import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResetProfilePanel from '../../src/components/settings/ResetProfilePanel'
import { INTELLIGENCE_STORAGE_KEY } from '../../src/modules/intelligence/intelligenceExport'
import { VIEWS, loadInitialView } from '../../src/modules/appNavigation'
import {
  RESET_KEEPS, RESET_REMOVES, buildProfileBackup, canRunReset, isResetConfirmed, requestProfileReset, setResetNotice, takeResetNotice,
} from '../../src/modules/profile/profileReset'
import { findSection } from '../../src/modules/settings/settingsRegistry'
import { STORAGE_KEY, getDefaultProfile, loadProfile } from '../../src/utils/storage'

vi.mock('../../src/context/ProfileContext', () => ({
  useProfile: () => ({ profile: getDefaultProfile(), resetProfile: () => {} }),
}))

let store
const KEPT = {
  'job-dashboard-discovered-jobs': '[{"id":"j1"}]',
  'job-dashboard-pipeline-state': '{"stage":"done"}',
  'job-dashboard-ai-settings': '{"provider":"ollama"}',
  'job-dashboard-ai-usage': '[]',
  'job-dashboard-ai-memory': '{}',
  'job-dashboard-sidebar-collapsed': 'true',
  'job-dashboard-theme': 'dark',
}

function oldProfile() {
  const p = getDefaultProfile()
  p.basicProfile.fullName = 'Jane Sample'
  p.basicProfile.email = 'jane@example.com'
  p.meta = { ...p.meta, onboardingComplete: true, completeProfileDismissedAt: '2026-11-01T10:00:00.000Z', onboardingFinishedEarly: true }
  p.questionnaire = { answers: [{ id: 10, question: 'Q10', answer: 'Startup' }] }
  p.cvLibrary = [{ id: 'cv1', label: 'Main CV' }]
  return p
}

const okResponse = (body = { ok: true, backup: 'data/profile.bak-20261101-090507' }) => ({ ok: true, json: async () => body })

beforeEach(() => {
  store = new Map(Object.entries(KEPT))
  store.set(STORAGE_KEY, JSON.stringify(oldProfile()))
  store.set(INTELLIGENCE_STORAGE_KEY, JSON.stringify({ meta: {}, scoringWeights: { roleMatch: 40 } }))
  vi.stubGlobal('localStorage', {
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('confirmation', () => {
  it('needs the exact word', () => {
    for (const text of ['', 'reset', 'RESET ', ' RESET', 'RESE', 'DELETE']) expect(isResetConfirmed(text), text).toBe(false)
    expect(isResetConfirmed('RESET')).toBe(true)
  })

  it('is disabled while running even with the right word', () => {
    expect(canRunReset('RESET', false)).toBe(true)
    expect(canRunReset('RESET', true)).toBe(false)
    expect(canRunReset('', false)).toBe(false)
  })

  it('does not call the server without the word', async () => {
    const fetchImpl = vi.fn()
    const result = await requestProfileReset('reset', { fetchImpl })
    expect(result.ok).toBe(false)
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(store.has(STORAGE_KEY)).toBe(true)
  })

  it('registers the section in the Danger zone and renders it with the dialog closed', () => {
    expect(findSection('reset-profile')).toMatchObject({ category: 'danger-zone', risky: 'delete' })
    const html = renderToStaticMarkup(h(ResetProfilePanel))
    expect(html).toContain('Reset profile')
    // The dialog is closed at first; the typed-word gate is exercised through canRunReset above.
    expect(html).not.toContain('Type RESET')
  })
})

describe('what is removed and kept', () => {
  it('lists both sides, and says the AI keys and jobs stay', () => {
    const removes = RESET_REMOVES.join(' ')
    const keeps = RESET_KEEPS.join(' ')
    expect(removes).toMatch(/Questionnaire answers/)
    expect(removes).toMatch(/CV library/)
    expect(removes).toMatch(/Complete your profile/)
    expect(keeps).toMatch(/Jobs/)
    expect(keeps).toMatch(/Applications/)
    expect(keeps).toMatch(/API keys/)
    expect(keeps).toMatch(/Findings store/)
  })

  it('removes only the two profile keys and leaves jobs, AI and layout keys untouched', async () => {
    const result = await requestProfileReset('RESET', { fetchImpl: async () => okResponse() })
    expect(result).toEqual({ ok: true, backup: 'data/profile.bak-20261101-090507' })
    expect(store.has(STORAGE_KEY)).toBe(false)
    expect(store.has(INTELLIGENCE_STORAGE_KEY)).toBe(false)
    for (const [key, value] of Object.entries(KEPT)) expect(store.get(key), key).toBe(value)
  })

  it('posts only the confirm word', async () => {
    const fetchImpl = vi.fn(async () => okResponse())
    await requestProfileReset('RESET', { fetchImpl })
    expect(fetchImpl).toHaveBeenCalledWith('/api/profile/reset', expect.objectContaining({ method: 'POST', body: '{"confirm":"RESET"}' }))
  })
})

describe('failure keeps the profile', () => {
  it.each([
    ['a failed backup', async () => ({ ok: false, status: 500, json: async () => ({ ok: false, code: 'backup_failed', error: 'x' }) }), 'The backup could not be made, so nothing was removed.'],
    ['an unreachable server', async () => { throw new Error('Jane Sample ECONNREFUSED') }, 'The reset did not run and nothing was removed.'],
    ['a body that is not JSON', async () => ({ ok: false, status: 502, json: async () => { throw new Error('bad') } }), 'The reset did not run and nothing was removed.'],
    ['an ok status without ok: true', async () => ({ ok: true, json: async () => ({}) }), 'The reset did not run and nothing was removed.'],
  ])('%s', async (_name, fetchImpl, text) => {
    const result = await requestProfileReset('RESET', { fetchImpl })
    expect(result).toEqual({ ok: false, error: text })
    expect(JSON.parse(store.get(STORAGE_KEY)).basicProfile.fullName).toBe('Jane Sample')
    expect(store.has(INTELLIGENCE_STORAGE_KEY)).toBe(true)
  })

  it('never shows text from the response', async () => {
    const result = await requestProfileReset('RESET', {
      fetchImpl: async () => ({ ok: false, json: async () => ({ ok: false, code: 'weird', error: 'Jane Sample leaked' }) }),
    })
    expect(result.error).not.toContain('Jane')
  })
})

describe('after a reset', () => {
  it('starts onboarding with a default profile and the old one does not reappear', async () => {
    await requestProfileReset('RESET', { fetchImpl: async () => okResponse() })
    const loaded = loadProfile()
    expect(loaded.basicProfile.fullName).toBe('')
    expect(loaded.questionnaire.answers).toEqual([])
    expect(loaded.cvLibrary ?? []).toHaveLength(0)
    expect(loaded.meta.onboardingComplete).toBe(false)
    expect(loaded.meta.completeProfileDismissedAt).toBeUndefined()
    expect(loadInitialView(loaded)).toBe(VIEWS.ONBOARDING)
  })

  it('holds the success text for the onboarding screen once', () => {
    setResetNotice('Profile reset.')
    expect(takeResetNotice()).toBe('Profile reset.')
    expect(takeResetNotice()).toBeNull()
  })
})

describe('download backup', () => {
  it('holds the profile and intelligence the browser has and no secret fields', () => {
    const backup = buildProfileBackup(oldProfile(), { meta: {}, scoringWeights: { roleMatch: 40 } }, new Date('2026-11-01T09:05:07Z'))
    expect(backup.kind).toBe('holojob-profile-backup')
    expect(backup.exportedAt).toBe('2026-11-01T09:05:07.000Z')
    expect(backup.profile.basicProfile.fullName).toBe('Jane Sample')
    expect(backup.profile._confidence).toBeUndefined()
    expect(backup.intelligence.scoringWeights.roleMatch).toBe(40)
    expect(JSON.stringify(backup)).not.toMatch(/apiKey|li_at|sk-/)
  })
})
