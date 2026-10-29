import { afterEach, describe, expect, it } from 'vitest'
import { dirtyDraftLabels, draftIsDirty, leaveDecision, setDraftDirty } from '../../src/modules/jobs/draftGuard'

afterEach(() => {
  setDraftDirty('a', 'x', false)
  setDraftDirty('b', 'y', false)
})

describe('draftIsDirty', () => {
  const base = { stage: 'applied', newNote: '', followUpDate: '' }

  it('is clean when nothing differs, treating undefined as empty', () => {
    expect(draftIsDirty(base, { ...base })).toBe(false)
    expect(draftIsDirty(base, { stage: 'applied' })).toBe(false)
  })

  it('is dirty when any field differs', () => {
    expect(draftIsDirty(base, { ...base, newNote: 'call back' })).toBe(true)
    expect(draftIsDirty(base, { ...base, stage: 'interview' })).toBe(true)
  })
})

describe('leaveDecision', () => {
  it('lets the owner leave without a question when nothing is dirty', () => {
    expect(leaveDecision([])).toBeNull()
  })

  it('names the unsaved forms in the question', () => {
    const question = leaveDecision(['application changes', 'CV record'])
    expect(question).toContain('application changes')
    expect(question).toContain('CV record')
  })
})

describe('dirty registry', () => {
  it('lists each label once and forgets a form that became clean', () => {
    setDraftDirty('a', 'application changes', true)
    setDraftDirty('b', 'application changes', true)
    expect(dirtyDraftLabels()).toEqual(['application changes'])
    setDraftDirty('a', 'application changes', false)
    setDraftDirty('b', 'application changes', false)
    expect(dirtyDraftLabels()).toEqual([])
  })
})
