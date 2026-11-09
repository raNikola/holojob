import { beforeAll, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  BOARD_HELP, BOARD_SUBTEXT, CONSENT_LABEL, canSave, changesFrom, consentSummary, draftFrom, turningOn,
} from '../../src/modules/sources/jobBoards.js'
import { migrateLegacyDiscoveryOptions, readLegacyDiscoveryOptions } from '../../src/modules/sources/sourcesClient.js'

// The test runner compiles JSX with the classic runtime, which needs React in scope.
let JobBoardChips
beforeAll(async () => {
  globalThis.React = React
  ;({ JobBoardChips } = await import('../../src/components/settings/JobBoardsPanel.jsx'))
})

const OFF = [
  { name: 'jobspy', optIn: false, inStandardRun: true, active: true },
  { name: 'wellfound', optIn: false, inStandardRun: false, active: true },
  { name: 'joberty', optIn: true, inStandardRun: false, active: false, consentAcceptedAt: null, history: [] },
]
const ON = OFF.map((b) => (b.name === 'joberty' ? { ...b, active: true, consentAcceptedAt: '2026-10-30T10:00:00+00:00' } : b))

describe('Joberty switch: draft and consent', () => {
  it('is off by default; every board is in the draft', () => {
    expect(draftFrom(OFF)).toEqual({ jobspy: true, wellfound: true, joberty: false })
    expect(changesFrom(draftFrom(OFF), OFF)).toBeNull()
    expect(canSave(draftFrom(OFF), OFF)).toBe(false)
  })

  it('switching on needs the consent line before Save sources is allowed', () => {
    const draft = { ...draftFrom(OFF), joberty: true }
    expect(turningOn(draft, OFF)).toEqual(['joberty'])
    expect(canSave(draft, OFF, {})).toBe(false)
    expect(canSave(draft, OFF, { joberty: true })).toBe(true)
    expect(changesFrom(draft, OFF, { joberty: true })).toEqual({ joberty: { active: true, consentAccepted: true } })
  })

  it('the request never carries a consent time; the server sets it', () => {
    expect(JSON.stringify(changesFrom({ ...draftFrom(OFF), joberty: true }, OFF, { joberty: true }))).not.toMatch(/At/)
  })

  it('switching off needs no consent and sends only active: false', () => {
    expect(turningOn({ ...draftFrom(ON), joberty: false }, ON)).toEqual([])
    expect(changesFrom({ ...draftFrom(ON), joberty: false }, ON)).toEqual({ joberty: { active: false } })
    expect(canSave({ ...draftFrom(ON), joberty: false }, ON)).toBe(true)
  })

  it('summarises the consent record, keeping it after a switch-off', () => {
    expect(consentSummary(OFF[2])).toBe('')
    expect(consentSummary(ON[2])).toBe('Terms accepted 2026-10-30')
    expect(consentSummary({ ...ON[2], active: false, disabledAt: '2026-10-31T09:00:00Z', migratedFrom: 'x' }))
      .toBe('Terms accepted 2026-10-30 · moved from the old Jobs-screen checkbox · switched off 2026-10-31')
  })
})

describe('Switching a source that follows the groups', () => {
  it('sends only { active }, needs no consent and can be saved at once', () => {
    const draft = { ...draftFrom(OFF), jobspy: false }
    expect(turningOn(draft, OFF)).toEqual([])
    expect(changesFrom(draft, OFF)).toEqual({ jobspy: { active: false } })
    expect(canSave(draft, OFF)).toBe(true)
  })

  it('switching it back on sends no consent flag', () => {
    const off = OFF.map((b) => (b.name === 'jobspy' ? { ...b, active: false } : b))
    expect(changesFrom({ ...draftFrom(off), jobspy: true }, off)).toEqual({ jobspy: { active: true } })
  })

  it('a switched-off source shows as off and says it is skipped', () => {
    const off = OFF.map((b) => (b.name === 'jobspy' ? { ...b, active: false } : b))
    const html = renderToStaticMarkup(createElement(JobBoardChips, { boards: off, draft: draftFrom(off), consent: {}, onToggle() {}, onConsent() {} }))
    expect(html).toMatch(/aria-checked="false"[^>]*>(?:(?!<\/button>).)*LinkedIn/)
    expect(html).toContain('Skipped by you')
  })
})

describe('Job boards chips', () => {
  const render = (boards, draft, consent = {}) => renderToStaticMarkup(createElement(JobBoardChips, { boards, draft, consent, onToggle() {}, onConsent() {} }))

  it('shows Joberty off with its subtext and tooltip; every switch is enabled', () => {
    const html = render(OFF, draftFrom(OFF))
    expect(html).toContain('Joberty')
    expect(html).toContain(BOARD_SUBTEXT.joberty)
    expect(html).toContain(BOARD_HELP.joberty.replaceAll("'", '&#x27;'))
    expect(html).toMatch(/aria-checked="false"[^>]*>(?:(?!<\/button>).)*Joberty/)
    expect(html).toContain('In the standard run')
    expect(html).toContain('Not in the standard run')
    expect(html).not.toContain('disabled=""')
    expect(html).not.toContain(CONSENT_LABEL)
  })

  it('carries the agreed texts', () => {
    expect(BOARD_SUBTEXT.joberty).toBe('Serbian IT board · Product Management')
    expect(BOARD_HELP.joberty).toBe("Reads Joberty's public API (Product Management category). Their terms (sections 7 and 8) restrict commercial and unauthorized use; check them before enabling.")
    expect(CONSENT_LABEL).toBe('I have read the terms')
  })

  it('switched on in the draft, it shows the one-line consent', () => {
    expect(render(OFF, { ...draftFrom(OFF), joberty: true })).toContain(`Joberty: ${CONSENT_LABEL}`)
    expect(render(ON, { ...draftFrom(ON) })).not.toContain(CONSENT_LABEL)
  })
})

const memory = (initial = {}) => {
  const items = new Map(Object.entries(initial))
  return { items, getItem: (k) => items.get(k) ?? null, setItem: (k, v) => items.set(k, v), removeItem: (k) => items.delete(k) }
}
const KEY = 'job-dashboard-discovery-options'

describe('the old Jobs-screen checkbox', () => {
  it('no key, no request', async () => {
    const calls = []
    const result = await migrateLegacyDiscoveryOptions({ storage: memory(), fetchImpl: async (...a) => { calls.push(a); return new Response('{}') } })
    expect(result).toEqual({ ok: true, migrated: false, present: false })
    expect(calls).toEqual([])
  })

  it('is handed to the server once and removed only after the server answered', async () => {
    const storage = memory({ [KEY]: '{"includeJoberty":true}' })
    const calls = []
    const fetchImpl = async (url, init) => {
      calls.push({ url, body: JSON.parse(init.body) })
      return new Response(JSON.stringify({ ok: true, migrated: true }), { status: 200 })
    }
    expect(await migrateLegacyDiscoveryOptions({ storage, fetchImpl })).toEqual({ ok: true, present: true, migrated: true })
    expect(calls).toEqual([{ url: '/api/sources/migrate-legacy', body: { value: { includeJoberty: true } } }])
    expect(storage.items.has(KEY)).toBe(false)
  })

  it('a failed hand-over leaves the browser value for the next try', async () => {
    const storage = memory({ [KEY]: '{"includeJoberty":true}' })
    const result = await migrateLegacyDiscoveryOptions({ storage, fetchImpl: async () => new Response('{"error":"down"}', { status: 500 }) })
    expect(result.ok).toBe(false)
    expect(storage.items.has(KEY)).toBe(true)
    expect((await migrateLegacyDiscoveryOptions({ storage, fetchImpl: async () => { throw new Error('offline') } })).ok).toBe(false)
    expect(storage.items.has(KEY)).toBe(true)
  })

  it('an unreadable value is passed as null, which the server never turns into a switch-on', () => {
    expect(readLegacyDiscoveryOptions(memory({ [KEY]: 'not json' }))).toEqual({ value: null })
  })
})

describe('the Jobs screen', () => {
  const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf8')

  it('has no Joberty checkbox and asks for the standard run only; the server decides about opt-in sources', () => {
    expect(screen).not.toMatch(/Joberty|DiscoverySourceOptions|discoveryProviders/)
    expect(screen).toContain("providers: 'serbia', country: searchCountry(profile, intelligence), intelligence, profile,")
    expect(screen).toContain("...(skipJobspyOnce ? { excludeProviders: ['jobspy'] } : {})")
  })

  it('the one-off skip is a plain checkbox that is not stored anywhere', () => {
    expect(screen).toContain('Skip LinkedIn this time')
    expect(screen).not.toMatch(/localStorage[^\n]*skipJobspy|skipJobspy[^\n]*localStorage/)
  })

  it('moves the old checkbox value once on load', () => {
    expect(screen).toContain('useEffect(() => { migrateLegacyDiscoveryOptions() }, [])')
  })

  it('Add job does not depend on the source switches', () => {
    for (const file of ['src/components/jobs/AddJobDialog.jsx', 'src/modules/jobs/manualJob.js']) {
      expect(fs.readFileSync(file, 'utf8')).not.toMatch(/sourcesClient|api\/sources|joberty/i)
    }
  })
})
