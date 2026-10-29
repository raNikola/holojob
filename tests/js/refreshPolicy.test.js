import { describe, expect, it } from 'vitest'
import { FOCUS_MIN_GAP_MS, POLL_MS, refreshDecision } from '../../src/modules/applications/refreshPolicy.js'
import { externalConflicts } from '../../src/modules/applications/trackerController.js'

const base = { visible: true, status: 'ready', dirtyLabels: [], sinceLastMs: 60_000 }

describe('refreshDecision', () => {
  it('refreshes when the tab becomes visible or focused', () => {
    expect(refreshDecision({ ...base, trigger: 'visible' })).toBe('refresh')
    expect(refreshDecision({ ...base, trigger: 'focus' })).toBe('refresh')
  })

  it('debounces a focus that follows a refresh closely (visible and focus fire together)', () => {
    expect(refreshDecision({ ...base, trigger: 'focus', sinceLastMs: FOCUS_MIN_GAP_MS - 1 })).toBe('skip')
    expect(refreshDecision({ ...base, trigger: 'focus', sinceLastMs: FOCUS_MIN_GAP_MS })).toBe('refresh')
  })

  it('polls about every 60 s, not sooner', () => {
    expect(refreshDecision({ ...base, trigger: 'poll', sinceLastMs: 5_000 })).toBe('skip')
    expect(refreshDecision({ ...base, trigger: 'poll', sinceLastMs: POLL_MS })).toBe('refresh')
  })

  it('never refreshes a hidden tab', () => {
    for (const trigger of ['visible', 'focus', 'poll']) expect(refreshDecision({ ...base, trigger, visible: false })).toBe('skip')
  })

  it('does not load the tracker for a view that never asked for it', () => {
    for (const status of ['idle', 'loading', 'error']) expect(refreshDecision({ ...base, trigger: 'focus', status })).toBe('skip')
  })

  it('waits while a new-application form holds input, since the application appearing would replace it', () => {
    expect(refreshDecision({ ...base, trigger: 'focus', dirtyLabels: ['new application'] })).toBe('skip')
    expect(refreshDecision({ ...base, trigger: 'focus', dirtyLabels: ['application changes'] })).toBe('refresh')
  })
})

describe('externalConflicts (the dirty-draft rule)', () => {
  const prev = { stage: 'applied', appliedDate: '2026-11-01', followUpDate: '', newNote: '' }

  it('flags a field edited here that moved to another value elsewhere', () => {
    const draft = { ...prev, stage: 'hr_screen' }
    expect(externalConflicts(prev, draft, { ...prev, stage: 'tech' })).toEqual(['stage'])
  })

  it('does not flag untouched fields, which simply follow the server', () => {
    expect(externalConflicts(prev, { ...prev }, { ...prev, stage: 'tech' })).toEqual([])
  })

  it('does not flag an edit that now equals the saved value, or a field that did not change elsewhere', () => {
    const draft = { ...prev, stage: 'tech', followUpDate: '2026-11-09' }
    expect(externalConflicts(prev, draft, { ...prev, stage: 'tech' })).toEqual([])
  })

  it('never flags the note box', () => {
    expect(externalConflicts(prev, { ...prev, newNote: 'typed' }, { ...prev, newNote: 'x' })).toEqual([])
  })
})
