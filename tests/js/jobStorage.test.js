import { describe, it, expect, vi } from 'vitest'
import { JOBS_STORAGE_KEY, saveJobs, slimJob } from '../../src/modules/jobs/jobStorage.js'

/** A storage that refuses any value longer than `limit` characters, as localStorage does past its quota. */
function storageWithLimit(limit) {
  const items = new Map()
  return {
    items,
    setItem(key, value) {
      if (value.length > limit) throw new DOMException('quota', 'QuotaExceededError')
      items.set(key, value)
    },
  }
}

const job = {
  jobId: 'a',
  title: 'Product Manager',
  status: 'saved',
  applicationTracking: { stage: 'applied' },
  description: 'x'.repeat(5000),
  llmFacts: { requirements: [{ text: 'y'.repeat(5000) }] },
  engineShadow: { fit: 60 },
}
const state = { meta: null, jobs: [job], filters: { searchText: '' }, importedAt: null }

describe('saveJobs', () => {
  it('stores the full list when it fits', () => {
    const storage = storageWithLimit(1e6)
    saveJobs(state, storage)
    expect(JSON.parse(storage.items.get(JOBS_STORAGE_KEY)).jobs[0].description).toBe(job.description)
  })

  it('stores the list without file fields when it does not fit, keeping what only the browser holds', () => {
    const storage = storageWithLimit(2000)
    saveJobs(state, storage)
    const saved = JSON.parse(storage.items.get(JOBS_STORAGE_KEY))
    expect(saved.slim).toBe(true)
    expect(saved.jobs[0]).toEqual({ jobId: 'a', title: 'Product Manager', status: 'saved', applicationTracking: { stage: 'applied' } })
    expect(saved.filters).toEqual({ searchText: '' })
  })

  it('does not throw when even the slim list does not fit', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const storage = storageWithLimit(10)
    expect(saveJobs(state, storage).jobs).toEqual([job])
    expect(storage.items.size).toBe(0)
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('slimJob leaves its input alone', () => {
    slimJob(job)
    expect(job.description).toBeDefined()
  })
})
