// @vitest-environment jsdom
// What the AI context reads of the whole list, when the browser holds only the ads the owner worked on (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P4 S5):
// the totals, the best-scored ads and the missing skills are the server's; without the server's list they are worked out from the browser's own rows as before.
// The context's privacy rules are unchanged: a job goes through `summarizeJob`, which is a whitelist.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SCORED, startListServer } from './setup/jobsListServer.js'

const SECRET = 'PRIVATE-NOTE-3319'
const realFetch = globalThis.fetch // the global one is replaced below; the server is reached through this
let server
let ctx // the modules, fresh for each test (the API probe and the context are module state)

async function load({ on, stored = [], health = true }) {
  vi.resetModules()
  vi.stubGlobal('fetch', async (url, options) => (String(url) === '/api/pipeline/health'
    ? { ok: health, status: health ? 200 : 503, json: async () => ({ available: health }) }
    : realFetch(`${server.base}${url}`, options)))
  const switchModule = await import('../../src/modules/jobs/serverListSwitch.js')
  switchModule.setServerListActive(on)
  const storage = await import('../../src/modules/jobs/jobStorage.js')
  localStorage.clear()
  storage.saveJobs({ ...storage.getDefaultJobsState(), jobs: stored }, localStorage)
  const api = await import('../../src/utils/apiAvailability.js')
  await api.ensureApiAvailable()
  ctx = await import('../../src/modules/ai/aiContextBuilder.js')
}

beforeEach(async () => { server = await startListServer({ pageSize: 4 }) })
afterEach(async () => {
  vi.unstubAllGlobals()
  await server.close()
})

const mine = { jobId: 'j00', title: 'My own copy', status: 'saved', matchScore: 99, matchLabel: 'Strong', priority: 'P1', applyRecommendation: 'Apply', notes: SECRET, outreach: { status: 'sent', contacts: [{ name: SECRET, email: `${SECRET}@x.example` }] } }

describe('with the server\'s list on', () => {
  it('the totals are the whole list\'s, not the few rows the browser holds', async () => {
    await load({ on: true, stored: [mine] })
    await ctx.prefetchJobContext()
    const context = ctx.buildAiContext({ featureId: 'careerStrategy' })
    expect(context.jobStats.total).toBe(12) // the scored list; the browser holds one row
    expect(context.jobStats.scored).toBe(12)
  })

  it('the best-scored ads are the server\'s, best first, summarised by the whitelist, with the owner\'s counts laid over the ones the browser holds', async () => {
    await load({ on: true, stored: [{ ...mine, jobId: SCORED[0].jobId }] })
    await ctx.prefetchJobContext()
    const { topJobs } = ctx.buildAiContext({ featureId: 'careerStrategy' })
    expect(topJobs.length).toBeLessThanOrEqual(10)
    const scores = topJobs.map((job) => job.matchScore)
    expect(scores).toEqual([...scores].sort((a, b) => b - a))
    expect(Math.max(...SCORED.map((r) => r.matchScore))).toBe(scores[0])
    for (const job of topJobs) {
      expect(job).not.toHaveProperty('jobUrl') // summarizeJob is a whitelist: no address, no facts
      expect(job).not.toHaveProperty('llmFacts')
    }
    expect(JSON.stringify(topJobs)).not.toContain(SECRET)
  })

  it('the skill gap counts the best-scored ads of the whole list', async () => {
    await load({ on: true, stored: [] })
    await ctx.prefetchJobContext()
    expect(ctx.buildSkillGapContext().jobCount).toBe(12)
  })

  it('an unreachable server leaves the context as the browser can work it out, and says nothing it does not know', async () => {
    await load({ on: true, stored: [mine] })
    await server.close()
    server = await startListServer({ pageSize: 4 })
    vi.stubGlobal('fetch', async () => { throw new Error('down') })
    expect(await ctx.prefetchJobContext()).toBeNull()
    expect(ctx.buildAiContext({ featureId: 'careerStrategy' }).jobStats.total).toBe(1)
  })
})

describe('with the server\'s list off', () => {
  it('nothing is asked of the server, and the context is the browser\'s own', async () => {
    await load({ on: false, stored: [mine] })
    const calls = []
    vi.stubGlobal('fetch', async (url, options) => { calls.push([url, options]); return realFetch(`${server.base}${url}`, options) })
    expect(await ctx.prefetchJobContext()).toBeNull()
    expect(calls).toEqual([])
    expect(ctx.buildAiContext({ featureId: 'careerStrategy' }).jobStats.total).toBe(1)
    expect(ctx.buildSkillGapContext().jobCount).toBe(1)
  })
})
