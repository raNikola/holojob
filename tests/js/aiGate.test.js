import { afterEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature as runAi } from '../../scripts/run-ai.js'
import { reserveAiCall, setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { describeRun } from '../../src/modules/jobs/pipelineSummary.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

// A request's `settings` are not read by the server; the selection is what it stores.
const runAiFeature = (args) => { selectProvider(args.settings); return runAi(args) }

const JOB = { jobId: 'j1', title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.' }

function gate(decision) {
  const seen = []
  setGateRunner(withSelection(async (command, input) => {
    seen.push({ command, input })
    if (command === 'reserve') return decision
    return { ok: true }
  }))
  return seen
}

// No test reads the server's real profile mirror.
setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))

useTempSecretStore()

afterEach(() => {
  setGateRunner()
  vi.restoreAllMocks()
})

describe('AI budget gate on the Node side', () => {
  it('asks the gate before a real call and makes none when refused', async () => {
    setAiSecret('openai', { key: CANARY })
    const seen = gate({ allowed: false, id: 'c1', reason: 'paid call openai refused: AI budget is 0' })
    const complete = vi.spyOn(getProvider('openai'), 'complete')
    const result = await runAiFeature({ feature: 'jobAnalysis', context: { job: JOB }, settings: { provider: 'openai', apiKey: 'k' } })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(result.error).toContain('AI budget is 0')
    expect(complete).not.toHaveBeenCalled()
    expect(seen.map((s) => s.command)).toEqual(['reserve'])
    expect(seen[0].input).toMatchObject({ provider: 'openai', feature: 'jobAnalysis', jobId: 'j1' })
    expect(seen[0].input.promptChars).toBeGreaterThan(0)
  })

  it('refuses the Claude Code CLI at budget 0 like any paid provider', async () => {
    gate({ allowed: false, id: 'c2', reason: 'paid call claude-code/default refused: AI budget is 0' })
    const complete = vi.spyOn(getProvider('claude-code'), 'complete')
    const result = await runAiFeature({ feature: 'coverLetter', context: { job: JOB }, settings: { provider: 'claude-code' } })
    expect(result.refused).toBe(true)
    expect(complete).not.toHaveBeenCalled()
  })

  it('records what an allowed call used', async () => {
    const seen = gate({ allowed: true, id: 'c3' })
    vi.spyOn(getProvider('ollama'), 'complete').mockResolvedValue({ text: '{}', usage: { inputTokens: 40, outputTokens: 7 } })
    const result = await runAiFeature({ feature: 'skillGap', context: {}, settings: { provider: 'ollama', baseUrl: 'http://localhost:11434' } })
    expect(result.ok).toBe(true)
    expect(seen.map((s) => s.command)).toEqual(['reserve', 'finish'])
    expect(seen[1].input).toMatchObject({ id: 'c3', ok: true, inputTokens: 40, outputTokens: 7 })
  })

  it('records a failed call once and does not retry it', async () => {
    const seen = gate({ allowed: true, id: 'c4' })
    const complete = vi.spyOn(getProvider('ollama'), 'complete').mockRejectedValue(new Error('connection refused'))
    const result = await runAiFeature({ feature: 'skillGap', context: {}, settings: { provider: 'ollama' } })
    expect(result.ok).toBe(false)
    expect(complete).toHaveBeenCalledTimes(1)
    expect(seen.filter((s) => s.command === 'finish')).toHaveLength(1)
    expect(seen[1].input).toMatchObject({ id: 'c4', ok: false })
  })

  it('does not gate or record the mock provider, which calls no model', async () => {
    const seen = gate({ allowed: false, reason: 'should not be asked' })
    const result = await runAiFeature({ feature: 'skillGap', context: {}, settings: { provider: 'mock' } })
    expect(result.ok).toBe(true)
    expect(seen).toEqual([])
  })

  it('fails closed when the gate cannot be asked', async () => {
    setGateRunner(async () => { throw new Error('python missing') })
    const decision = await reserveAiCall({ provider: 'openai', promptChars: 10, feature: 'chat' })
    expect(decision.allowed).toBe(false)
    expect(decision.reason).toContain('AI gate unavailable')
  })

  it('checks Claude Code health without sending a prompt', async () => {
    const provider = getProvider('claude-code')
    const complete = vi.spyOn(provider, 'complete')
    await provider.healthCheck()
    expect(complete).not.toHaveBeenCalled()
  })
})

describe('pipeline summary', () => {
  it('says when the result is reduced quality', () => {
    const line = describeRun({ discovery: { deduped: 5 }, enrichment: { enrichedShare: 0 }, quality: { reduced: true, reason: 'AI enrichment refused: AI budget is 0' } }, 5)
    expect(line).toContain('REDUCED QUALITY (AI enrichment refused: AI budget is 0)')
  })
})
