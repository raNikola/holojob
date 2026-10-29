import { describe, expect, it } from 'vitest'
import { DEFAULT_WORK_STAGES } from '../../src/modules/applications/applicationEnums.js'
import {
  RegistryError,
  applyStageOperation,
  boardColumn,
  defaultSettings,
  keyForLabel,
  labelFor,
  mergeBackupSettings,
  moveTargets,
  reorderDecision,
  retiredStages,
  activeStages,
  selectableStageKeys,
  settingsProblem,
  withChange,
} from '../../src/modules/applications/stageRegistry.js'

const folded = (over = {}) => ({ voided: false, outcome: null, stage: 'applied', ...over })

describe('stage registry (pure)', () => {
  it('defaults are valid and are not shared between callers', () => {
    const a = defaultSettings()
    expect(settingsProblem(a)).toBeNull()
    a.stages.work[0].label = 'changed'
    expect(defaultSettings().stages.work).toEqual(DEFAULT_WORK_STAGES)
  })

  it('names the selectable stages and the move targets', () => {
    const settings = defaultSettings()
    expect(selectableStageKeys(settings)).toEqual(['applied', 'screen', 'tech', 'onsite', 'offer'])
    expect(moveTargets(settings)).toEqual(['applied', 'screen', 'tech', 'onsite', 'offer', 'rejected', 'ghosted'])
    const { settings: retired } = applyStageOperation(settings, { op: 'retire', key: 'offer' })
    expect(moveTargets(retired)).not.toContain('offer')
  })

  it('places a folded application on the board', () => {
    const settings = applyStageOperation(defaultSettings(), { op: 'retire', key: 'offer' }).settings
    expect(boardColumn(folded({ voided: true, outcome: 'rejected' }), settings)).toBeNull()
    expect(boardColumn(folded({ outcome: 'rejected', stage: 'tech' }), settings)).toBe('rejected')
    expect(boardColumn(folded({ outcome: 'ghosted' }), settings)).toBe('ghosted')
    for (const outcome of ['withdrawn', 'offer_accepted', 'offer_declined', 'position_closed']) {
      expect(boardColumn(folded({ outcome }), settings)).toBe('closed')
    }
    expect(boardColumn(folded(), settings)).toBe('applied')
    expect(boardColumn(folded({ stage: 'tech' }), settings)).toBe('tech')
    expect(boardColumn(folded({ stage: 'offer' }), settings)).toBe('unfiled') // retired
    expect(boardColumn(folded({ stage: 'gone' }), settings)).toBe('unfiled') // unknown
  })

  it('resolves labels for fixed, active, retired and unknown keys', () => {
    const settings = applyStageOperation(defaultSettings(), { op: 'retire', key: 'offer' }).settings
    expect(['applied', 'rejected', 'ghosted', 'unfiled', 'tech', 'offer', 'zzz'].map((k) => labelFor(k, settings))).toEqual([
      'Applied', 'Rejected', 'Ghosted', 'Unfiled', 'Tech', 'Offer', 'zzz',
    ])
  })

  it('slugs keys and suffixes on collision with any key, retired or reserved', () => {
    const settings = defaultSettings()
    expect(keyForLabel('Technical Interview', settings)).toBe('technical_interview')
    expect(keyForLabel('Tech', settings)).toBe('tech_2')
    expect(keyForLabel('Applied', settings)).toBe('applied_2')
    expect(keyForLabel('???', settings)).toBe('stage')
    expect(keyForLabel('Ünïcödé', settings)).toBe('unicode')
  })

  it('operations return a new object and leave the input alone', () => {
    const settings = defaultSettings()
    const copy = structuredClone(settings)
    for (const op of [{ op: 'add', label: 'X' }, { op: 'rename', key: 'tech', label: 'T' }, { op: 'move', key: 'tech', dir: 'down' }, { op: 'retire', key: 'screen' }]) {
      applyStageOperation(settings, op)
      expect(settings).toEqual(copy)
    }
  })

  it('retire asks the caller for the open count and refuses with it', () => {
    try {
      applyStageOperation(defaultSettings(), { op: 'retire', key: 'tech' }, (key) => (key === 'tech' ? 3 : 0))
      throw new Error('should have refused')
    } catch (e) {
      expect(e).toBeInstanceOf(RegistryError)
      expect(e).toMatchObject({ status: 409, extra: { count: 3 } })
    }
  })

  it('move skips retired stages and does nothing at an edge', () => {
    let settings = applyStageOperation(defaultSettings(), { op: 'retire', key: 'tech' }).settings
    settings = applyStageOperation(settings, { op: 'move', key: 'onsite', dir: 'up' }).settings
    expect(settings.stages.work.map((s) => s.key)).toEqual(['onsite', 'tech', 'screen', 'offer'])
    expect(applyStageOperation(settings, { op: 'move', key: 'onsite', dir: 'up' }).change).toBeNull()
  })

  it('keeps only the last 50 changes', () => {
    let settings = defaultSettings()
    for (let i = 0; i < 60; i += 1) settings = withChange(settings, { action: 'rename', key: 'tech', old: `${i}`, new: `${i + 1}` }, '2026-11-03T10:00:00.000Z')
    expect(settings.changes).toHaveLength(50)
    expect(settings.changes[0].old).toBe('10')
  })

  it('merges a backup without dropping or reordering anything', () => {
    const current = applyStageOperation(defaultSettings(), { op: 'rename', key: 'tech', label: 'Technical' }).settings
    const backup = { ...defaultSettings(), stages: { work: [{ key: 'x', label: 'X', retired: false, interview: true }, ...defaultSettings().stages.work] } }
    const { settings, added } = mergeBackupSettings(current, backup, '2026-11-03T10:00:00.000Z')
    expect(added).toEqual(['x'])
    expect(settings.stages.work.slice(0, 4)).toEqual(current.stages.work)
    expect(settings.stages.work[4]).toEqual({ key: 'x', label: 'X', retired: true, interview: true })
    expect(mergeBackupSettings(settings, backup, 'later').added).toEqual([])
  })
})

describe('reorderDecision (dragging work columns in Settings)', () => {
  const settings = defaultSettings()
  const keys = activeStages(settings).map((s) => s.key)

  /** Replays the ops through the same function the route runs, as the server would. */
  const replay = (start, ops) => ops.reduce((cur, op) => applyStageOperation(cur, op).settings, start)

  it('the same position is a no-op', () => {
    expect(reorderDecision(settings, keys[1], keys[1])).toEqual({ action: 'none', reason: 'same-position' })
  })

  it('refuses a fixed column or an unknown key, as source or target', () => {
    for (const fixed of ['applied', 'rejected', 'ghosted', 'no-such-stage']) {
      expect(reorderDecision(settings, fixed, keys[0]).reason).toBe('fixed')
      expect(reorderDecision(settings, keys[0], fixed).reason).toBe('fixed')
    }
  })

  it('refuses while a request is in flight or tracking is off', () => {
    expect(reorderDecision(settings, keys[0], keys[1], { busy: true }).reason).toBe('busy')
    expect(reorderDecision(settings, keys[0], keys[1], { trackingEnabled: false }).reason).toBe('tracking-off')
  })

  it('sends one single-step move per place passed, and the existing route produces the dropped order', () => {
    const last = keys.length - 1
    const down = reorderDecision(settings, keys[0], keys[last])
    expect(down.ops).toHaveLength(last)
    expect(down.ops.every((o) => o.op === 'move' && o.dir === 'down' && o.key === keys[0])).toBe(true)
    expect(activeStages(replay(settings, down.ops)).map((s) => s.key)).toEqual([...keys.slice(1), keys[0]])

    const up = reorderDecision(settings, keys[last], keys[0])
    expect(up.ops.every((o) => o.dir === 'up')).toBe(true)
    expect(activeStages(replay(settings, up.ops)).map((s) => s.key)).toEqual([keys[last], ...keys.slice(0, last)])
  })

  it('counts only active stages, so a retired one in between does not add a step', () => {
    const withRetired = applyStageOperation(settings, { op: 'retire', key: keys[1] }).settings
    const active = activeStages(withRetired).map((s) => s.key)
    const decision = reorderDecision(withRetired, active[0], active[1])
    expect(decision.ops).toHaveLength(1)
    expect(activeStages(replay(withRetired, decision.ops)).map((s) => s.key)).toEqual([active[1], active[0], ...active.slice(2)])
    expect(retiredStages(withRetired).map((s) => s.key)).toEqual([keys[1]])
    expect(reorderDecision(withRetired, active[0], keys[1]).reason).toBe('fixed')
  })
})
