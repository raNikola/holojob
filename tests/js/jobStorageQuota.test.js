import { beforeEach, describe, expect, it, vi } from 'vitest'
import { JOBS_STORAGE_KEY, onJobsSaved, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { getStorageHealth, resetStorageHealth, STORAGE_QUOTA_CHARS } from '../../src/modules/jobs/storageHealth.js'
import { resetJobTexts } from '../../src/modules/jobs/jobTexts.js'

/** A storage that refuses a value past `limit` characters, as localStorage does, and keeps the previous value when it refuses. */
function storageWithLimit(limit, initial = {}) {
  const items = new Map(Object.entries(initial))
  return {
    items,
    get length() { return items.size },
    key: (i) => [...items.keys()][i] ?? null,
    getItem: (k) => items.get(k) ?? null,
    setItem(key, value) {
      if (value.length > limit) throw new DOMException('quota', 'QuotaExceededError')
      items.set(key, value)
    },
  }
}

const big = (n) => 'x'.repeat(n)
const row = (jobId, extra = {}) => ({
  jobId, title: `T ${jobId}`, status: 'saved', notes: `note ${jobId}`, outreach: { contacts: [{ name: 'A' }] },
  applicationTracking: { stage: 'applied' }, tailoredAssets: { resume: 'r.pdf' }, aiInsights: { jobAnalysis: { x: 1 } },
  description: big(1000), llmFacts: { f: big(1000) }, engineShadow: { fit: big(500) }, ...extra,
})
const stateOf = (jobs) => ({ meta: null, jobs, filters: { searchText: '' }, importedAt: null })
const stored = (storage) => JSON.parse(storage.items.get(JOBS_STORAGE_KEY))

beforeEach(() => { resetStorageHealth(); resetJobTexts(); vi.restoreAllMocks() })

describe('saveJobs tiers', () => {
  const jobs = [row('listed'), row('kept', { keptByUser: true }), row('off', { offList: true }), row('mine', { manualEntry: true })]
  const sizeOf = (list) => JSON.stringify({ meta: null, jobs: list, filters: { searchText: '' }, importedAt: null }).length

  it('far below the limit stores everything and says ok', () => {
    const storage = storageWithLimit(STORAGE_QUOTA_CHARS)
    const result = saveJobs(stateOf(jobs), storage)
    expect(result.tier).toBe('full')
    expect(stored(storage).degraded).toBeUndefined()
    expect(stored(storage).jobs).toEqual(jobs)
    expect(getStorageHealth().level).toBe('ok')
  })

  it('past 85% of the limit still stores everything but says near', () => {
    const storage = storageWithLimit(STORAGE_QUOTA_CHARS, { other: big(Math.ceil(STORAGE_QUOTA_CHARS * 0.86)) })
    expect(saveJobs(stateOf(jobs), storage).tier).toBe('full')
    expect(getStorageHealth().level).toBe('near')
  })

  it('just over the limit stores lean: drops facts and the text of listed rows, keeps the text of kept, off-list and hand-entered rows', () => {
    const storage = storageWithLimit(sizeOf(jobs) - 1)
    expect(saveJobs(stateOf(jobs), storage).tier).toBe('lean')
    const saved = stored(storage)
    expect(saved.degraded).toBe('lean')
    const by = Object.fromEntries(saved.jobs.map((j) => [j.jobId, j]))
    expect(by.listed.description).toBeUndefined()
    for (const id of ['kept', 'off', 'mine']) expect(by[id].description).toBe(big(1000))
    for (const j of saved.jobs) { expect(j.llmFacts).toBeUndefined(); expect(j.engineShadow).toBeUndefined() }
    expect(getStorageHealth().level).toBe('lean')
  })

  it('over lean stores minimal: only hand-entered rows keep their text', () => {
    const lean = JSON.stringify({ meta: null, jobs: jobs.map(({ llmFacts, engineShadow, ...r }) => (r.keptByUser || r.offList || r.manualEntry ? r : { ...r, description: undefined })), filters: { searchText: '' }, importedAt: null, slim: true, degraded: 'lean' })
    const storage = storageWithLimit(lean.length - 1)
    expect(saveJobs(stateOf(jobs), storage).tier).toBe('minimal')
    const by = Object.fromEntries(stored(storage).jobs.map((j) => [j.jobId, j]))
    expect(by.mine.description).toBe(big(1000))
    for (const id of ['listed', 'kept', 'off']) expect(by[id].description).toBeUndefined()
    expect(getStorageHealth()).toMatchObject({ level: 'minimal', droppedText: 3 })
  })

  it('no shape drops a field the browser alone holds', () => {
    for (const limit of [STORAGE_QUOTA_CHARS, sizeOf(jobs) - 1, 6000]) {
      const storage = storageWithLimit(limit)
      const result = saveJobs(stateOf(jobs), storage)
      if (!result.saved) continue
      for (const [i, j] of stored(storage).jobs.entries()) {
        for (const f of ['status', 'notes', 'outreach', 'applicationTracking', 'tailoredAssets', 'aiInsights', 'title']) expect(j[f]).toEqual(jobs[i][f])
      }
    }
  })

  it('over minimal writes nothing, keeps the previous value, reports error and does not claim success', () => {
    const previous = JSON.stringify({ jobs: [{ jobId: 'old' }], marker: 'PREVIOUS' })
    const storage = storageWithLimit(50, { [JOBS_STORAGE_KEY]: previous })
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const listener = vi.fn()
    const off = onJobsSaved(listener)
    const result = saveJobs(stateOf(jobs), storage)
    expect(result.saved).toBe(false)
    expect(storage.items.get(JOBS_STORAGE_KEY)).toBe(previous)
    expect(getStorageHealth().level).toBe('error')
    expect(listener).not.toHaveBeenCalled()
    off()
  })

  it('the error level is not cleared by reading the older copy', async () => {
    const { loadJobs } = await import('../../src/modules/jobs/jobStorage.js')
    const storage = storageWithLimit(50)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    saveJobs(stateOf(jobs), storage)
    expect(getStorageHealth().level).toBe('error')
    loadJobs()
    expect(getStorageHealth().level).toBe('error')
  })
})
