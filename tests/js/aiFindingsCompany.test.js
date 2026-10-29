import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkAiFinding, runAiFeature as runAi } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import {
  DEFAULT_FRESHNESS_DAYS, PROMPT_VERSIONS, companyEntityKey, findingsRoot, normalizeCompanyName,
} from '../../scripts/ai-findings-store.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { analysisButtonState } from '../../src/modules/ai/findingStatus.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

// Fake people: nothing here is real.
const OWNER = { name: 'Zlatan Qwerty', email: 'zlatan.qwerty@owner-test.example' }
const ANSWER = '{"companySummary":"A software company","cultureInsights":["remote"],"risks":[]}'

const job = (over = {}) => ({
  jobId: 'wk-1', title: 'Senior PM', company: 'Acme d.o.o.', location: 'Remote', matchScore: 80,
  description: 'Own the roadmap.', ...over,
})
const context = (jobOver = {}, top = {}) => ({ profile: { currentRole: 'PM' }, memory: [], job: job(jobOver), ...top })

useTempSecretStore()

let gateCalls
let complete
let selection

const run = (ctx = context(), extra = {}) => {
  selectProvider(selection)
  return runAi({ feature: 'companyIntelligence', context: ctx, ...extra })
}
const dir = () => path.join(findingsRoot(), 'company')
const fileOf = (name = 'Acme') => path.join(dir(), `${companyEntityKey(name)}.json`)
const reserves = () => gateCalls.filter((c) => c.command === 'reserve')

beforeEach(() => {
  selection = { provider: 'openai', model: 'model-a' }
  setAiSecret('openai', { key: CANARY })
  setIdentitySource(() => ({ names: [OWNER.name], emails: [OWNER.email], phones: [], links: [] }))
  gateCalls = []
  setGateRunner(withSelection(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? { allowed: true, id: 'c1' } : { ok: true }
  }))
  complete = vi.spyOn(getProvider('openai'), 'complete').mockImplementation(async () => ({ text: ANSWER, usage: {} }))
  vi.spyOn(console, 'info').mockImplementation(() => {})
})

afterEach(() => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
})

describe('company name normalization', () => {
  it.each([
    ['Acme d.o.o.', 'acme'], ['ACME Ltd', 'acme'], ['  Acme ', 'acme'], ['Ačme GmbH', 'acme'], ['Acme, Inc.', 'acme'],
    ['Smith & Sons Co.', 'smith sons'], ['Beograd Soft d.o.o. Beograd', 'beograd soft doo beograd'], ['S.r.l.', 'srl'],
    ['Ltd', 'ltd'], ['', ''], [null, ''],
  ])('%j -> %j', (input, expected) => {
    expect(normalizeCompanyName(input)).toBe(expected)
  })

  it('the key is 16 hex, equal for spellings of one company and different for another', () => {
    expect(companyEntityKey('Acme d.o.o.')).toMatch(/^[0-9a-f]{16}$/)
    expect(companyEntityKey('Acme d.o.o.')).toBe(companyEntityKey('ACME'))
    expect(companyEntityKey('Acme')).not.toBe(companyEntityKey('Acme Labs'))
    expect(companyEntityKey('')).toBeNull()
  })
})

describe('company findings in front of the gate', () => {
  it('a miss goes through the gate and is stored under the company entity', async () => {
    const result = await run()
    expect(result).toMatchObject({ ok: true, data: { companySummary: 'A software company' } })
    expect(result.cached).toBeUndefined()
    expect(result.findingId).toBe(`${companyEntityKey('Acme')}:1`)
    expect(reserves()).toHaveLength(1)
    expect(reserves()[0].input).toMatchObject({ feature: 'companyIntelligence' })
    expect(JSON.parse(fs.readFileSync(fileOf(), 'utf-8')).entity).toEqual({ type: 'company', key: companyEntityKey('Acme') })
  })

  it('a hit reserves nothing and calls no provider; a new posting, score, profile or spelling of the same company is a hit', async () => {
    await run()
    gateCalls.length = 0
    complete.mockClear()
    const same = [
      context(),
      context({ jobId: 'wk-2', title: 'Director', description: 'A different posting.', matchScore: 10 }),
      context({ company: 'ACME Ltd' }),
      context({}, { profile: { currentRole: 'Director' }, memory: [{ note: 'x' }] }),
    ]
    for (const ctx of same) expect(await run(ctx)).toMatchObject({ ok: true, cached: true })
    expect(gateCalls.filter((c) => c.command !== 'selection-get')).toEqual([])
    expect(complete).not.toHaveBeenCalled()
  })

  it('another company is a miss', async () => {
    await run()
    const result = await run(context({ company: 'Globex' }))
    expect(result.cached).toBeUndefined()
    expect(reserves()).toHaveLength(2)
    expect(fs.readdirSync(dir())).toHaveLength(2)
  })

  it('a changed model misses and appends a second finding', async () => {
    await run()
    selection = { provider: 'openai', model: 'model-b' }
    expect((await run()).findingId).toMatch(/:2$/)
    expect(reserves()).toHaveLength(2)
  })

  it('a bumped prompt version misses', async () => {
    await run()
    PROMPT_VERSIONS.companyIntelligence = '2'
    try {
      expect((await run()).cached).toBeUndefined()
      expect(reserves()).toHaveLength(2)
    } finally {
      PROMPT_VERSIONS.companyIntelligence = '1'
    }
  })

  it('refresh goes to the gate and appends', async () => {
    await run()
    expect((await run(context(), { refresh: true })).findingId).toMatch(/:2$/)
  })

  it('is fresh for 29 days, a miss after 31 that appends, and nothing is deleted', async () => {
    expect(DEFAULT_FRESHNESS_DAYS.companyIntelligence).toBe(30)
    await run()
    const age = (days) => {
      const record = JSON.parse(fs.readFileSync(fileOf(), 'utf-8'))
      record.findings.at(-1).at = new Date(Date.now() - days * 86400000).toISOString()
      fs.writeFileSync(fileOf(), JSON.stringify(record))
    }
    age(29)
    expect(await run()).toMatchObject({ cached: true })
    age(31)
    gateCalls.length = 0
    const result = await run()
    expect(result.cached).toBeUndefined()
    expect(result.findingId).toMatch(/:2$/)
    expect(reserves()).toHaveLength(1)
    expect(JSON.parse(fs.readFileSync(fileOf(), 'utf-8')).findings).toHaveLength(2)
  })

  it('a refused budget still refuses on a miss; a stored finding is still served', async () => {
    setGateRunner(withSelection(async (command) => (command === 'reserve' ? { allowed: false, reason: 'budget is 0' } : { ok: true })))
    expect(await run()).toMatchObject({ ok: false, refused: true })
    expect(fs.existsSync(dir())).toBe(false)
  })

  it('a job without a company is not stored', async () => {
    await run(context({ company: '' }))
    expect(fs.existsSync(dir())).toBe(false)
  })
})

describe('what reaches the file', () => {
  it('no prompt text, no identifier, no key, no company name', async () => {
    await run(context({ description: `Write to ${OWNER.email}, ${OWNER.name}` }))
    const text = fs.readFileSync(fileOf(), 'utf-8')
    for (const secret of [CANARY, OWNER.email, OWNER.name, 'Zlatan', 'owner-test.example', 'Own the roadmap', 'Senior PM', 'Acme', 'acme', 'wk-1']) {
      expect(text).not.toContain(secret)
    }
    expect(JSON.parse(text).findings[0]).not.toHaveProperty('prompt')
    expect(fs.readdirSync(dir())).toEqual([`${companyEntityKey('Acme')}.json`])
  })

  it('an answer that echoes an identifier is returned once but not stored', async () => {
    complete.mockResolvedValueOnce({ text: `{"companySummary":"Contact ${OWNER.email}"}`, usage: {} })
    const result = await run()
    expect(result.ok).toBe(true)
    expect(result.warning).toContain('not stored')
    expect(fs.existsSync(dir())).toBe(false)
  })
})

describe('the check and the button', () => {
  it('is fresh for any job of the same company, and not for another company or another model', async () => {
    selectProvider(selection)
    expect((await checkAiFinding({ feature: 'companyIntelligence', context: context() })).fresh).toBe(false)
    await run()
    const fresh = await checkAiFinding({ feature: 'companyIntelligence', context: context({ jobId: 'wk-2', description: 'Other', company: 'Acme Ltd' }) })
    expect(fresh).toMatchObject({ fresh: true, model: 'model-a' })
    expect(Object.keys(fresh).sort()).toEqual(['at', 'fresh', 'model'])
    expect((await checkAiFinding({ feature: 'companyIntelligence', context: context({ company: 'Globex' }) })).fresh).toBe(false)
    selectProvider({ provider: 'openai', model: 'model-b' })
    expect((await checkAiFinding({ feature: 'companyIntelligence', context: context() })).fresh).toBe(false)
    expect(reserves()).toHaveLength(1) // only the one real run reserved; the checks asked the gate nothing
  })

  it('an expired finding is not fresh', async () => {
    await run()
    const record = JSON.parse(fs.readFileSync(fileOf(), 'utf-8'))
    record.findings[0].at = new Date(Date.now() - 31 * 86400000).toISOString()
    fs.writeFileSync(fileOf(), JSON.stringify(record))
    selectProvider(selection)
    expect((await checkAiFinding({ feature: 'companyIntelligence', context: context() })).fresh).toBe(false)
  })

  it('the button says researched, and stays usable when this job has no result on screen yet', () => {
    const status = { fresh: true, at: '2026-10-29T10:00:00.000Z', model: 'model-a' }
    const shown = analysisButtonState({ status, hasAnalysis: true, loading: false, verb: 'researched' })
    expect(shown.disabled).toBe(true)
    expect(shown.title).toContain('Already researched on')
    expect(analysisButtonState({ status, hasAnalysis: false, loading: false, verb: 'researched' }).disabled).toBe(false)
  })
})
