// A save the server refuses (the save guard, 409 would_lose_data) is announced to the user, whichever screen made it, also when the
// caller ignores the result (`void saveIntelligenceToDataDir(...)`). The event carries which file, never content.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SAVE_REFUSED_EVENT, announceSaveRefused, refusedNoticeText } from '../../src/modules/jobs/saveRefused.js'
import { saveIntelligenceToDataDir } from '../../src/modules/jobs/intelligenceSync.js'
import { saveProfileToDataDir, syncMessages, syncProfileWithStatus } from '../../src/modules/jobs/profileSync.js'

const CANARY = 'CANARY-PROFILE-TEXT-9921'
const refusal = (what) => ({ error: `Save refused: it would empty or cut 5 ${what} settings`, code: 'would_lose_data', fields: ['x'] })

let events
let onEvent
beforeEach(() => {
  events = []
  const target = new EventTarget()
  globalThis.window = target
  onEvent = (e) => events.push(e.detail)
  target.addEventListener(SAVE_REFUSED_EVENT, onEvent)
})
afterEach(() => { delete globalThis.window; vi.restoreAllMocks(); vi.unstubAllGlobals() })

const stubFetch = (saveStatus, body) => vi.stubGlobal('fetch', vi.fn(async (url) => {
  if (url === '/api/pipeline/health') return { ok: true, status: 200, json: async () => ({ available: true }) }
  return { ok: saveStatus < 300, status: saveStatus, json: async () => body }
}))

describe('the refusal is announced', () => {
  it('announce does nothing without a window and sends only which file', () => {
    delete globalThis.window
    expect(() => announceSaveRefused('profile')).not.toThrow()
    globalThis.window = new EventTarget()
    const seen = []
    globalThis.window.addEventListener(SAVE_REFUSED_EVENT, (e) => seen.push(e.detail))
    announceSaveRefused('intelligence')
    expect(seen).toEqual([{ what: 'intelligence' }])
  })

  it('the intelligence save announces a refusal and still returns the failure', async () => {
    stubFetch(409, refusal('intelligence'))
    const result = await saveIntelligenceToDataDir({ languages: ['x'] })
    expect(result.ok).toBe(false)
    expect(events).toEqual([{ what: 'intelligence' }])
  })

  it('the profile save announces a refusal', async () => {
    stubFetch(409, refusal('profile'))
    const result = await saveProfileToDataDir({ basicProfile: { fullName: CANARY }, resume: {}, meta: {} })
    expect(result.ok).toBe(false)
    expect(events).toEqual([{ what: 'profile' }])
  })

  it('another failure is not announced as a refusal', async () => {
    stubFetch(400, { error: 'Invalid profile payload' })
    await saveProfileToDataDir({ basicProfile: {}, resume: {}, meta: {} })
    expect(events).toEqual([])
  })

  it('the Review screen check announces it and says so on its line, with a fixed text', async () => {
    const fetchFn = vi.fn(async (url) => (url === '/api/profile/save'
      ? { ok: false, status: 409, json: async () => refusal('profile') }
      : { ok: true, status: 200, json: async () => ({ available: true }) }))
    const result = await syncProfileWithStatus({ basicProfile: { fullName: CANARY }, resume: {}, meta: {} }, { fetchFn })
    const lines = syncMessages(result).map((l) => l.text).join(' ')
    expect(events).toEqual([{ what: 'profile' }])
    expect(lines).toContain('HTTP 409')
    expect(lines).toContain('refused the save')
    expect(lines).not.toContain(CANARY)
  })

  it('the notice text names no setting value', () => {
    expect(refusedNoticeText('profile')).toContain('Nothing was changed')
    expect(refusedNoticeText('intelligence')).toContain('data/backups/auto')
  })
})
