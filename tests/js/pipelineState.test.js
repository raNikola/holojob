import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'
import {
  derivePipelineStateFromHealth,
  loadPipelineState,
  syncPipelineCounts,
  updatePipelineState,
} from '../../src/modules/jobs/pipelineState.js'

const HEALTH_WITHOUT_COUNTS = { available: true, discovery: {}, scoring: {}, tailoring: {} }
const HEALTH_WITH_COUNTS = {
  available: true,
  discovery: { jobCount: 7, generatedAt: 'd1' },
  scoring: { jobCount: 5, generatedAt: 's1' },
  tailoring: { tailoredCount: 2 },
}
const LOADED_JOBS = [
  { jobId: 'a', matchScore: 80, tailoredAssets: { resumeMd: 'x' } },
  { jobId: 'b', matchScore: 60 },
  { jobId: 'c' },
]

describe('pipeline counts follow the current jobs', () => {
  const real = globalThis.localStorage
  let setItem

  beforeEach(() => {
    const data = new Map()
    setItem = vi.fn((key, value) => data.set(key, value))
    globalThis.localStorage = { getItem: (key) => data.get(key) ?? null, setItem }
  })
  afterEach(() => { globalThis.localStorage = real })

  it('jobs that arrive after the first write replace the first-render counts', () => {
    updatePipelineState(derivePipelineStateFromHealth(HEALTH_WITHOUT_COUNTS, []))
    expect(loadPipelineState().jobsDiscovered).toBe(0)

    const next = syncPipelineCounts(HEALTH_WITHOUT_COUNTS, LOADED_JOBS)

    expect(next).toMatchObject({ jobsDiscovered: 3, jobsScored: 2, resumesGenerated: 1 })
    expect(loadPipelineState()).toMatchObject({ jobsDiscovered: 3, jobsScored: 2, resumesGenerated: 1 })
  })

  it('writes nothing and returns null when no count changed, so it cannot loop', () => {
    syncPipelineCounts(HEALTH_WITHOUT_COUNTS, LOADED_JOBS)
    setItem.mockClear()

    const edited = LOADED_JOBS.map((job) => ({ ...job, status: 'saved' }))
    expect(syncPipelineCounts(HEALTH_WITHOUT_COUNTS, edited)).toBeNull()
    expect(setItem).not.toHaveBeenCalled()
  })

  it('counts from the server win over the job list: a changed list writes nothing', () => {
    updatePipelineState(derivePipelineStateFromHealth(HEALTH_WITH_COUNTS, []))
    setItem.mockClear()

    expect(syncPipelineCounts(HEALTH_WITH_COUNTS, LOADED_JOBS)).toBeNull()
    expect(setItem).not.toHaveBeenCalled()
    expect(loadPipelineState()).toMatchObject({ jobsDiscovered: 7, jobsScored: 5, resumesGenerated: 2 })
  })

  it('older health never writes back over the fresher counts auto-refresh stored', () => {
    updatePipelineState(derivePipelineStateFromHealth(HEALTH_WITH_COUNTS, LOADED_JOBS))
    setItem.mockClear()
    const older = { discovery: { jobCount: 6 }, scoring: { jobCount: 4 }, tailoring: { tailoredCount: 0 } }

    expect(syncPipelineCounts(older, LOADED_JOBS)).toBeNull()
    expect(setItem).not.toHaveBeenCalled()
    expect(loadPipelineState()).toMatchObject({ jobsDiscovered: 7, jobsScored: 5, resumesGenerated: 2 })
  })

  it('with partial health only the unreported count follows the jobs', () => {
    updatePipelineState({ jobsDiscovered: 7, jobsScored: 0, resumesGenerated: 2 })
    const partial = { discovery: { jobCount: 6 }, scoring: {}, tailoring: { tailoredCount: 0 } }

    expect(syncPipelineCounts(partial, LOADED_JOBS)).toMatchObject({ jobsDiscovered: 7, jobsScored: 2, resumesGenerated: 2 })
  })

  it('touches only the counts: run times and the running step stay', () => {
    updatePipelineState({ lastTailoringRun: 't1', lastDiscoveryRun: 'd2', runningStep: 'scoring' })

    const next = syncPipelineCounts(HEALTH_WITHOUT_COUNTS, LOADED_JOBS)

    expect(next).toMatchObject({ lastTailoringRun: 't1', lastDiscoveryRun: 'd2', runningStep: 'scoring', jobsDiscovered: 3 })
  })

  it('the screen derives from the stored list on mount and syncs on every change of health or jobs', () => {
    const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf8')
    const mount = screen.slice(screen.indexOf('autoLoadJobs(loadJobs())'), screen.indexOf('usePipelineAutoRefresh({'))
    expect(mount).toContain('derivePipelineStateFromHealth(probe.health, loadJobs().jobs)')
    expect(mount).not.toContain('probe.health, state.jobs')
    expect(mount).toMatch(/syncPipelineCounts\(health, state\.jobs\)[\s\S]*\}, \[health, state\.jobs\]\)/)
  })
})
