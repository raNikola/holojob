import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { runAiFeature } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { buildAiContext, buildAiRedactionHints } from '../../src/modules/ai/aiContextBuilder.js'
import { REGENERATE_CONFIRM, analysisButtonState, fetchFindingStatus, regenerateDecision } from '../../src/modules/ai/findingStatus.js'
import { setAiSecret, setSecretsRoot } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

const realFetch = globalThis.fetch
const secrets = useTempSecretStore()
const ANSWER = '{"fitSummary":"Good fit","riskLevel":"low"}'
const JOB = { jobId: 'wk-1', title: 'Senior PM', company: 'Acme', matchScore: 80, description: 'Own the roadmap.', applicationTracking: { interviewStage: 'Applied' } }
const context = (job = {}) => ({ profile: { currentRole: 'PM' }, memory: [], job: { ...JOB, ...job } })

let server
let base
let gateCalls
let complete

beforeEach(async () => {
  gateCalls = []
  setGateRunner(withSelection(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? { allowed: true, id: 'c1' } : { ok: true }
  }))
  setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
  setAiSecret('openai', { key: CANARY })
  selectProvider({ provider: 'openai', model: 'model-a' })
  complete = vi.spyOn(getProvider('openai'), 'complete').mockResolvedValue({ text: ANSWER, usage: {} })
  vi.spyOn(console, 'info').mockImplementation(() => {})
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
  await new Promise((r) => server.close(r))
})

const check = async (ctx, feature = 'jobAnalysis') => {
  const res = await realFetch(`${base}/api/ai/findings/check`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feature, context: ctx }),
  })
  return { status: res.status, body: await res.json() }
}
const nonGate = () => gateCalls.filter((c) => c.command !== 'selection-get')

describe('POST /api/ai/findings/check', () => {
  it('a miss answers fresh: false and touches nothing', async () => {
    const { status, body } = await check(context())
    expect(status).toBe(200)
    expect(body).toEqual({ fresh: false, at: null, model: null })
    expect(nonGate()).toEqual([])
    expect(complete).not.toHaveBeenCalled()
  })

  it('a hit answers { fresh, at, model } only, with no call, no reservation and no key', async () => {
    const stored = await runAiFeature({ feature: 'jobAnalysis', context: context() })
    expect(stored.findingId).toBeTruthy()
    gateCalls.length = 0
    complete.mockClear()
    setSecretsRoot(`${secrets.dir}-gone`)
    const { body } = await check(context())
    expect(Object.keys(body).sort()).toEqual(['at', 'fresh', 'model'])
    expect(body).toMatchObject({ fresh: true, model: 'model-a' })
    expect(Date.parse(body.at)).not.toBeNaN()
    expect(nonGate()).toEqual([])
    expect(complete).not.toHaveBeenCalled()
  })

  it.each([
    ['the posting', { description: 'Own the roadmap and the budget.' }],
    ['the score', { matchScore: 50 }],
    ['the stage', { applicationTracking: { interviewStage: 'Offer' } }],
  ])('a changed %s is a miss again', async (_n, change) => {
    await runAiFeature({ feature: 'jobAnalysis', context: context() })
    expect((await check(context())).body.fresh).toBe(true)
    expect((await check(context(change))).body.fresh).toBe(false)
  })

  it('a changed profile and a changed model are misses', async () => {
    await runAiFeature({ feature: 'jobAnalysis', context: context() })
    expect((await check({ ...context(), profile: { currentRole: 'Director' } })).body.fresh).toBe(false)
    selectProvider({ provider: 'openai', model: 'model-b' })
    expect((await check(context())).body.fresh).toBe(false)
  })

  it('the memory the app merges after an analysis does not make it stale', async () => {
    await runAiFeature({ feature: 'jobAnalysis', context: context() })
    expect((await check({ ...context(), memory: [{ note: 'new strength' }] })).body.fresh).toBe(true)
  })

  it('answers not fresh for a feature without a store, no selection, and the mock provider', async () => {
    await runAiFeature({ feature: 'jobAnalysis', context: context() })
    expect((await check(context(), 'skillGap')).body.fresh).toBe(false)
    selectProvider({ provider: 'mock' })
    expect((await check(context())).body.fresh).toBe(false)
    selectProvider()
    expect((await check(context())).body.fresh).toBe(false)
  })

  it('goes through the request guard: wrong content type is refused', async () => {
    const res = await realFetch(`${base}/api/ai/findings/check`, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: '{}' })
    expect(res.status).toBe(415)
  })
})

describe('the browser asks with the same context it runs with', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete globalThis.localStorage
  })

  it('fetchFindingStatus is fresh after a run built from the same job, and not fresh once the job changes', async () => {
    const data = new Map([
      ['job-dashboard-candidate-profile', JSON.stringify({ basicProfile: { currentRole: 'PM' }, completion: {} })],
      ['job-dashboard-discovered-jobs', JSON.stringify({ jobs: [JOB] })],
    ])
    globalThis.localStorage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) }
    vi.stubGlobal('fetch', (url, init) => realFetch(`${base}${url}`, init))
    const browserContext = (job) => ({ ...buildAiContext({ featureId: 'jobAnalysis', job }), redactionHints: buildAiRedactionHints({ job }) })

    expect((await fetchFindingStatus('jobAnalysis', { job: JOB })).fresh).toBe(false)
    await runAiFeature({ feature: 'jobAnalysis', context: browserContext(JOB) })
    // The app merges the analysis into its memory afterwards; that must not matter.
    data.set('job-dashboard-ai-memory', JSON.stringify({ identifiedStrengths: ['roadmaps'] }))
    expect(await fetchFindingStatus('jobAnalysis', { job: JOB })).toMatchObject({ fresh: true, model: 'model-a' })
    expect((await fetchFindingStatus('jobAnalysis', { job: { ...JOB, description: 'Changed posting.' } })).fresh).toBe(false)
  })
})

describe('analysis button state', () => {
  const fresh = { fresh: true, at: '2026-10-29T10:00:00.000Z', model: 'model-a' }

  it('is disabled with the date and model in the tooltip when the analysis is valid and on screen', () => {
    const state = analysisButtonState({ status: fresh, hasAnalysis: true, loading: false })
    expect(state.disabled).toBe(true)
    expect(state.title).toContain('model-a')
    expect(state.title).toContain('nothing has changed')
    expect(state.title).toMatch(/Already analysed on .*2026|Already analysed on .*29/)
  })

  it('is enabled when nothing is stored, when the stored one is outdated, or before the answer arrives', () => {
    for (const status of [{ fresh: false, at: null, model: null }, null, undefined]) {
      expect(analysisButtonState({ status, hasAnalysis: true, loading: false })).toMatchObject({ disabled: false })
    }
  })

  it('stays enabled when a valid finding exists but no analysis is shown (the click is a free hit)', () => {
    expect(analysisButtonState({ status: fresh, hasAnalysis: false, loading: false }).disabled).toBe(false)
  })

  it('is disabled while a call runs', () => {
    expect(analysisButtonState({ status: null, hasAnalysis: false, loading: true }).disabled).toBe(true)
  })

  it('becomes enabled as soon as a key input changes (status turns not fresh)', () => {
    expect(analysisButtonState({ status: fresh, hasAnalysis: true, loading: false }).disabled).toBe(true)
    expect(analysisButtonState({ status: { fresh: false, at: null, model: null }, hasAnalysis: true, loading: false }).disabled).toBe(false)
  })
})

describe('regenerate decision', () => {
  const fresh = { fresh: true, at: '2026-10-29T10:00:00.000Z', model: 'model-a' }
  const stale = { fresh: false, at: null, model: null }

  it('is disabled and ignored while a call runs, and while one has just been started', () => {
    for (const status of [fresh, stale, null]) {
      expect(regenerateDecision({ status, loading: true })).toEqual({ disabled: true, action: 'ignore' })
      expect(regenerateDecision({ status, loading: false, inFlight: true })).toEqual({ disabled: true, action: 'ignore' })
    }
  })

  it('asks first when the finding is still valid', () => {
    expect(regenerateDecision({ status: fresh, loading: false })).toEqual({ disabled: false, action: 'confirm' })
    expect(REGENERATE_CONFIRM).toBe('Nothing has changed since the last analysis. Regenerating makes a new AI call that counts against your limit. Continue?')
  })

  it('runs straight away when nothing valid is stored or the status is unknown', () => {
    for (const status of [stale, null, undefined]) {
      expect(regenerateDecision({ status, loading: false })).toEqual({ disabled: false, action: 'run' })
    }
  })

  it('after a confirmed regenerate further clicks are ignored until it finishes, then allowed again', () => {
    let inFlight = false
    const click = () => regenerateDecision({ status: fresh, loading: false, inFlight }).action
    expect(click()).toBe('confirm')
    inFlight = true // run() sets it synchronously
    expect(click()).toBe('ignore')
    expect(click()).toBe('ignore')
    inFlight = false // finished
    expect(click()).toBe('confirm')
  })
})
