import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  validate: vi.fn(),
  regenerate: vi.fn(),
  save: vi.fn(),
  sync: vi.fn(),
}))

vi.mock('../../src/modules/intelligence/intelligenceValidators', () => ({ validateProfileForIntelligence: mocks.validate }))
vi.mock('../../src/modules/intelligence/intelligenceExport', () => ({ regenerateIntelligence: mocks.regenerate, saveIntelligence: mocks.save }))
vi.mock('../../src/modules/jobs/intelligenceSync', () => ({ saveIntelligenceToDataDir: mocks.sync }))

const { regenerateAndSync } = await import('../../src/modules/cvs/regenerateAfterApply')

beforeEach(() => {
  vi.clearAllMocks()
  mocks.validate.mockReturnValue({ valid: true, errors: [] })
  mocks.regenerate.mockReturnValue({ generated: true })
  mocks.sync.mockResolvedValue({ ok: true })
})

describe('regenerateAndSync', () => {
  it('regenerates, keeps it in the browser and syncs it, like the button', async () => {
    expect(await regenerateAndSync({ p: 1 })).toEqual({ ok: true })
    expect(mocks.regenerate).toHaveBeenCalledWith({ p: 1 })
    expect(mocks.save).toHaveBeenCalledWith({ generated: true })
    expect(mocks.sync).toHaveBeenCalledWith({ generated: true })
  })
  it('stops with the validation errors when required profile fields are missing', async () => {
    mocks.validate.mockReturnValue({ valid: false, errors: ['Email is required.', 'Complete all 17 questionnaire answers.'] })
    const result = await regenerateAndSync({})
    expect(result).toEqual({ ok: false, error: 'Email is required. Complete all 17 questionnaire answers.' })
    expect(mocks.regenerate).not.toHaveBeenCalled()
    expect(mocks.sync).not.toHaveBeenCalled()
  })
  it('reports a generator failure', async () => {
    mocks.regenerate.mockImplementation(() => { throw new Error('boom') })
    expect(await regenerateAndSync({})).toEqual({ ok: false, error: 'boom' })
    expect(mocks.sync).not.toHaveBeenCalled()
  })
  it('reports a failed sync as not synced, not as success', async () => {
    mocks.sync.mockResolvedValue({ ok: false, reason: 'API unavailable' })
    const result = await regenerateAndSync({})
    expect(result.ok).toBe(false)
    expect(result.error).toContain('not synced to disk: API unavailable')
  })
})
