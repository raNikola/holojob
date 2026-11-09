import fs from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import { describeFailure, syncMessages, syncProfileWithStatus } from '../../src/modules/jobs/profileSync.js'

const CANARY = 'CANARY-PROFILE-TEXT-4471'
const PROFILE = { basicProfile: { fullName: CANARY }, resume: {}, meta: {} }

/** A fetch that answers the two calls independently. `save` and `health` are a status, 'network' or { status, body }. */
function server({ save, health }) {
  const answer = (spec, defaults) => {
    if (spec === 'network') throw new TypeError(`fetch failed ${CANARY}`)
    const { status, body } = typeof spec === 'number' ? { status: spec, body: defaults } : spec
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  }
  return vi.fn(async (url) => (url === '/api/profile/save' ? answer(save, { ok: true }) : answer(health, { available: true })))
}
const run = async (spec) => {
  const fetchFn = server(spec)
  const result = await syncProfileWithStatus(PROFILE, { fetchFn })
  return { result, lines: syncMessages(result), fetchFn }
}
const texts = (lines) => lines.map((l) => l.text)

describe('the Review screen sync check: the save and the status are separate', () => {
  it('save ok, status ok: one success line', async () => {
    const { lines } = await run({ save: 200, health: 200 })
    expect(lines).toEqual([{ tone: 'ok', text: 'Synced to data/profile/candidate-profile.json' }])
  })

  it('save ok, status fails: says it was saved, and only that the status could not be confirmed', async () => {
    const { lines } = await run({ save: 200, health: 503 })
    expect(lines.map((l) => l.tone)).toEqual(['ok', 'warn'])
    expect(texts(lines)[0]).toBe('Saved to data/profile/candidate-profile.json.')
    expect(texts(lines)[1]).toMatch(/Server status could not be confirmed \(HTTP 503/)
    expect(texts(lines).join(' ')).not.toMatch(/not synced|could not be saved|not saved/i)
  })

  it('save ok, the status says "not available": still not a failed save', async () => {
    const { lines } = await run({ save: 200, health: { status: 200, body: { available: false } } })
    expect(texts(lines)[1]).toBe('Server status could not be confirmed (the server says it is not available).')
    expect(lines[0].tone).toBe('ok')
  })

  it('save fails, status ok: says the save failed, with the status, and nothing about the server being down', async () => {
    const { lines } = await run({ save: 500, health: 200 })
    expect(lines).toHaveLength(1)
    expect(lines[0].tone).toBe('error')
    expect(lines[0].text).toMatch(/^Not synced: the profile could not be saved to the server \(HTTP 500: the server failed while handling it; check its log\)\.$/)
  })

  it('both fail: two separate error lines, each with its own status', async () => {
    const { lines } = await run({ save: 403, health: 403 })
    expect(lines).toHaveLength(2)
    expect(lines.every((l) => l.tone === 'error')).toBe(true)
    expect(texts(lines)[0]).toMatch(/could not be saved to the server \(HTTP 403: the server refused this web address; open the app from an address listed in HOLOJOB_ALLOWED_ORIGINS\)/)
    expect(texts(lines)[1]).toMatch(/Server status could not be confirmed \(HTTP 403/)
  })

  it('both calls are always made, whatever the other answers (the save is not skipped because the status failed)', async () => {
    for (const spec of [{ save: 200, health: 403 }, { save: 413, health: 200 }, { save: 'network', health: 'network' }]) {
      const { fetchFn } = await run(spec)
      expect(fetchFn.mock.calls.map(([url]) => url).sort()).toEqual(['/api/pipeline/health', '/api/profile/save'])
    }
  })

  it('a network failure is "no answer", per call, and a save can succeed while the status call cannot connect', async () => {
    const { lines } = await run({ save: 'network', health: 'network' })
    expect(texts(lines)[0]).toContain('(no answer: the server could not be reached)')
    expect(texts(lines)[1]).toContain('(no answer: the server could not be reached)')
    const mixed = await run({ save: 200, health: 'network' })
    expect(mixed.lines.map((l) => l.tone)).toEqual(['ok', 'warn'])
  })

  it('shows nothing the server sent and nothing from the profile', async () => {
    const { lines, fetchFn } = await run({ save: { status: 400, body: { error: `Invalid profile ${CANARY} /app/data/profile` } }, health: { status: 500, body: { error: CANARY } } })
    expect(texts(lines).join(' ')).not.toContain('CANARY')
    expect(texts(lines).join(' ')).not.toContain('/app/data')
    const posted = JSON.parse(fetchFn.mock.calls.find(([url]) => url === '/api/profile/save')[1].body)
    expect(posted.profile.basicProfile.fullName).toBe(CANARY) // the profile goes to the server as it always did ...
    expect(texts(lines).join(' ')).not.toContain(CANARY) // ... and never comes back onto the screen
  })

  it('describes a status with a fixed hint, and an unknown 4xx with the status alone', () => {
    expect(describeFailure({ status: 0 })).toBe('no answer: the server could not be reached')
    expect(describeFailure({ status: 415 })).toMatch(/^HTTP 415: /)
    expect(describeFailure({ status: 404 })).toBe('HTTP 404')
  })
})

describe('the Review screen uses it', () => {
  const source = fs.readFileSync('src/components/review/ReviewScreen.jsx', 'utf8')

  it('no longer hides the result behind the cached availability flag, and reports a failed export sync', () => {
    expect(source).not.toMatch(/isApiAvailable/)
    expect(source).toMatch(/syncProfileWithStatus\(profile\)\.then\(\(result\) =>/)
    expect(source).toMatch(/syncMessages\(outcome\)/)
    expect(source).toMatch(/role="status"/)
  })
})
