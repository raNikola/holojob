import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature as runAi } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import {
  DEFAULT_FRESHNESS_DAYS, PROMPT_VERSIONS, appendFinding, assertAppendOnly, findingsRoot, jobEntityKey, lookupFinding,
} from '../../scripts/ai-findings-store.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

// Fake people: nothing here is real.
const OWNER = { name: 'Zlatan Qwerty', email: 'zlatan.qwerty@owner-test.example' }
const ANSWER = '{"fitSummary":"Good fit","strengths":["roadmaps"],"riskLevel":"low","confidence":"high"}'

const JOB = {
  jobId: 'wk-12345678901', title: 'Senior Product Manager', company: 'Acme', matchScore: 81,
  description: 'Own the roadmap. Salary 80000-120000 EUR.',
  applicationTracking: { applied: true, interviewStage: 'HR Screen' },
}
const baseContext = (over = {}) => ({
  profile: { currentRole: 'Product Manager', skills: ['Roadmapping'] },
  memory: [{ note: 'prefers remote' }],
  job: { ...JOB, ...over.job },
  ...over.top,
})

useTempSecretStore()

let gateCalls
let complete
let selection

const run = (context = baseContext(), extra = {}) => {
  selectProvider(selection)
  return runAi({ feature: 'jobAnalysis', context, ...extra })
}
const findingsDir = () => path.join(findingsRoot(), 'job')

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

const reserves = () => gateCalls.filter((c) => c.command === 'reserve')

describe('findings store in front of the budget gate', () => {
  it('a miss goes through the gate, calls the provider and stores the answer', async () => {
    const result = await run()
    expect(result).toMatchObject({ ok: true, data: { fitSummary: 'Good fit' } })
    expect(result.cached).toBeUndefined()
    expect(result.findingId).toBe(`${jobEntityKey(JOB.jobId)}:1`)
    expect(reserves()).toHaveLength(1)
    expect(complete).toHaveBeenCalledTimes(1)
  })

  it('a hit reserves nothing, calls no provider, writes no ledger row, needs no key, and is logged', async () => {
    await run()
    gateCalls.length = 0
    complete.mockClear()
    // The key is gone: a stored answer is still served.
    fs.rmSync(process.env.CAREER_OS_SECRETS_DIR, { recursive: true, force: true })
    const { setSecretsRoot } = await import('../../scripts/secret-store.js')
    setSecretsRoot(path.join(findingsDir(), '..', 'no-secrets'))
    const result = await run()
    expect(result).toMatchObject({ ok: true, cached: true, data: { fitSummary: 'Good fit' } })
    expect(result.findingId).toMatch(/:1$/)
    expect(gateCalls.filter((c) => c.command !== 'selection-get')).toEqual([])
    expect(complete).not.toHaveBeenCalled()
    expect(console.info).toHaveBeenCalledWith(expect.stringContaining('hit jobAnalysis'))
  })

  it.each([
    ['the model', () => { selection = { provider: 'openai', model: 'model-b' } }],
    ['a profile summary', null, { top: { profile: { currentRole: 'Director', skills: ['Roadmapping'] } } }],
    ['the posting', null, { job: { description: 'Own the roadmap. Salary 90000 EUR.' } }],
    ['the job score', null, { job: { matchScore: 40 } }],
    ['the stage', null, { job: { applicationTracking: { applied: true, interviewStage: 'Offer' } } }],
    ['the memory', null, { top: { memory: [{ note: 'prefers on-site' }] } }],
  ])('changing %s misses and appends a second finding', async (_name, change, over) => {
    await run()
    change?.()
    const result = await run(over ? baseContext(over) : baseContext())
    expect(result.cached).toBeUndefined()
    expect(result.findingId).toMatch(/:2$/)
    expect(reserves()).toHaveLength(2)
  })

  it('an input beyond the truncated prompt text still changes the key', async () => {
    const long = 'x '.repeat(7000)
    await run(baseContext({ job: { description: `${long}A` } }))
    const result = await run(baseContext({ job: { description: `${long}B` } }))
    expect(result.cached).toBeUndefined()
    expect(reserves()).toHaveLength(2)
  })

  it('a bumped prompt version misses', async () => {
    await run()
    PROMPT_VERSIONS.jobAnalysis = '2'
    try {
      const result = await run()
      expect(result.cached).toBeUndefined()
      expect(reserves()).toHaveLength(2)
    } finally {
      PROMPT_VERSIONS.jobAnalysis = '1'
    }
  })

  it('refresh goes to the gate and appends; the old finding stays', async () => {
    await run()
    const result = await run(baseContext(), { refresh: true })
    expect(result.findingId).toMatch(/:2$/)
    expect(reserves()).toHaveLength(2)
    const record = JSON.parse(fs.readFileSync(path.join(findingsDir(), `${jobEntityKey(JOB.jobId)}.json`), 'utf-8'))
    expect(record.findings.map((f) => f.seq)).toEqual([1, 2])
  })

  it('jobAnalysis has no expiry: a very old finding is still a hit', async () => {
    expect(DEFAULT_FRESHNESS_DAYS.jobAnalysis).toBeNull()
    await run()
    const file = path.join(findingsDir(), `${jobEntityKey(JOB.jobId)}.json`)
    const record = JSON.parse(fs.readFileSync(file, 'utf-8'))
    record.findings[0].at = '2020-01-01T00:00:00.000Z'
    fs.writeFileSync(file, JSON.stringify(record))
    expect(await run()).toMatchObject({ ok: true, cached: true, foundAt: '2020-01-01T00:00:00.000Z' })
    expect(reserves()).toHaveLength(1)
  })

  it('a feature with a freshness window: older than it is a miss and stays on disk, newer is a hit', async () => {
    await run()
    const entityKey = jobEntityKey(JOB.jobId)
    const file = path.join(findingsDir(), `${entityKey}.json`)
    const { cacheKey, at } = JSON.parse(fs.readFileSync(file, 'utf-8')).findings[0]
    const later = (days) => Date.parse(at) + days * 86400000
    const look = (days, freshnessDays) => lookupFinding({ feature: 'jobAnalysis', entityKey, cacheKey, now: later(days), freshnessDays })
    expect(look(6, 7).hit).toBe(true)
    expect(look(8, 7)).toEqual({ hit: false, reason: 'stale' })
    expect(look(8, null).hit).toBe(true)
    expect(JSON.parse(fs.readFileSync(file, 'utf-8')).findings).toHaveLength(1)
  })

  it('a refused budget still refuses on a miss and stores nothing', async () => {
    setGateRunner(withSelection(async (command) => (command === 'reserve' ? { allowed: false, reason: 'budget is 0' } : { ok: true })))
    const result = await run()
    expect(result).toMatchObject({ ok: false, refused: true, error: 'budget is 0' })
    expect(complete).not.toHaveBeenCalled()
    expect(fs.existsSync(findingsDir())).toBe(false)
  })

  it('a stored finding is served even when the budget is now 0 (a hit is not a call)', async () => {
    await run()
    setGateRunner(withSelection(async (command) => (command === 'reserve' ? { allowed: false, reason: 'budget is 0' } : { ok: true })))
    expect(await run()).toMatchObject({ ok: true, cached: true })
  })

  it('a failed provider call stores nothing', async () => {
    complete.mockRejectedValueOnce(new Error('boom'))
    expect(await run()).toMatchObject({ ok: false })
    expect(fs.existsSync(findingsDir())).toBe(false)
  })

  it('features without a store and the mock provider never touch it', async () => {
    selectProvider(selection)
    await runAi({ feature: 'skillGap', context: baseContext() })
    selection = { provider: 'mock' }
    vi.spyOn(getProvider('mock'), 'complete').mockResolvedValue({ text: ANSWER, usage: {} })
    await run()
    expect(fs.existsSync(findingsDir())).toBe(false)
  })

  it('a job without an id is not stored', async () => {
    await run(baseContext({ job: { jobId: undefined } }))
    expect(fs.existsSync(findingsDir())).toBe(false)
  })
})

describe('what reaches the file', () => {
  it('holds no key and no personal identifier, and the prompt text is not stored', async () => {
    const context = baseContext({ job: { description: `Write to ${OWNER.email}, ${OWNER.name} says hi` } })
    await run(context)
    const text = fs.readFileSync(path.join(findingsDir(), `${jobEntityKey(JOB.jobId)}.json`), 'utf-8')
    for (const secret of [CANARY, OWNER.email, OWNER.name, 'Zlatan', 'Qwerty', 'owner-test.example']) expect(text).not.toContain(secret)
    const record = JSON.parse(text)
    expect(record.findings[0]).not.toHaveProperty('prompt')
    expect(record.findings[0]).toMatchObject({ inputHash: expect.stringMatching(/^[0-9a-f]{64}$/), cacheKey: expect.stringContaining('|1|') })
    expect(text).not.toContain('Own the roadmap')
    expect(text).not.toContain('[EMAIL]')
    expect(record.entity).toEqual({ type: 'job', key: jobEntityKey(JOB.jobId) })
    // The job id is part of the prompt the provider gets; the entity key and file name are opaque.
    expect(fs.readdirSync(findingsDir())).toEqual([`${jobEntityKey(JOB.jobId)}.json`])
    expect(record.entity.key).not.toContain(JOB.jobId)
  })

  it('an answer that echoes an identifier is returned once but not stored', async () => {
    complete.mockResolvedValueOnce({ text: `{"fitSummary":"Write to ${OWNER.email}"}`, usage: {} })
    const result = await run()
    expect(result.ok).toBe(true)
    expect(result.warning).toContain('not stored')
    expect(result.findingId).toBeUndefined()
    expect(fs.existsSync(findingsDir())).toBe(false)
  })

  it('an answer that looks like a credential is not stored', () => {
    const saved = appendFinding({
      feature: 'jobAnalysis', entityKey: 'aaaaaaaaaaaaaaaa', promptVersion: '1', inputHash: 'h', cacheKey: 'k',
      result: { note: `token sk-${'a1'.repeat(10)}` },
    })
    expect(saved.stored).toBe(false)
  })

  it('files are private (dir 700, file 600)', async () => {
    await run()
    const file = path.join(findingsDir(), `${jobEntityKey(JOB.jobId)}.json`)
    expect(fs.statSync(file).mode & 0o777).toBe(0o600)
    expect(fs.statSync(findingsDir()).mode & 0o777).toBe(0o700)
  })
})

describe('append-only', () => {
  const entry = (seq) => ({ id: `k:${seq}`, seq, cacheKey: 'c' })
  it('rejects an edit, a removal and a seq gap', () => {
    const prev = { findings: [entry(1), entry(2)] }
    expect(() => assertAppendOnly(prev, { findings: [entry(1), entry(2), entry(3)] })).not.toThrow()
    expect(() => assertAppendOnly(prev, { findings: [entry(1)] })).toThrow(/removed/)
    expect(() => assertAppendOnly(prev, { findings: [entry(1), { ...entry(2), cacheKey: 'x' }] })).toThrow(/edited/)
    expect(() => assertAppendOnly(prev, { findings: [entry(1), entry(2), entry(5)] })).toThrow(/seq/)
  })

  it('a damaged file is never overwritten; the call is a miss that goes through the gate', async () => {
    await run()
    const file = path.join(findingsDir(), `${jobEntityKey(JOB.jobId)}.json`)
    fs.writeFileSync(file, '{ not json')
    const result = await run()
    expect(result.ok).toBe(true)
    expect(result.cached).toBeUndefined()
    expect(result.warning).toContain('unreadable')
    expect(fs.readFileSync(file, 'utf-8')).toBe('{ not json')
    expect(lookupFinding({ feature: 'jobAnalysis', entityKey: jobEntityKey(JOB.jobId), cacheKey: 'x' })).toEqual({ hit: false, reason: 'unreadable' })
  })
})
