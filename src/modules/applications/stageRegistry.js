/**
 * The stage registry of the application tracker (docs/redesign/TRACKER_PLAN.md 1.6, 1.7).
 *
 * Work stages have a key that is created once and never changes, and a label the owner
 * can rename. A stage is retired, never deleted, so every event that names a key stays
 * readable. Pure: no I/O, no clock. The store (scripts/application-store.js) reads and
 * writes the settings file and runs the open-application count under its lock.
 */

import {
  CLOSED_COLUMNS,
  DEFAULT_WORK_STAGES,
  FIRST_STAGE,
  MAX_ACTIVE_WORK_STAGES,
  MAX_STAGE_LABEL,
  RESERVED_STAGE_KEYS,
  STAGE_KEY,
  UNFILED,
} from './applicationEnums.js'

export const SETTINGS_VERSION = 1
export const MAX_CHANGES = 50

const FIXED_LABELS = {
  [FIRST_STAGE]: 'Applied',
  rejected: 'Rejected',
  ghosted: 'Ghosted',
  [UNFILED]: 'Unfiled',
}

/** A refused registry operation. `status` is the HTTP status the route answers with. */
export class RegistryError extends Error {
  constructor(status, message, extra = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

export function defaultSettings() {
  return {
    version: SETTINGS_VERSION,
    updatedAt: null,
    trackingEnabled: true,
    followUpReminders: true,
    stages: { work: DEFAULT_WORK_STAGES.map((s) => ({ ...s })) },
    changes: [],
  }
}

/** Returns a message when `settings` is not a well-formed settings object, else null. */
export function settingsProblem(settings) {
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)) return 'not an object'
  if (settings.version !== SETTINGS_VERSION) return `unknown version ${settings.version}`
  if (typeof settings.trackingEnabled !== 'boolean') return 'trackingEnabled must be true or false'
  if (typeof settings.followUpReminders !== 'boolean') return 'followUpReminders must be true or false'
  const work = settings.stages?.work
  if (!Array.isArray(work)) return 'stages.work must be a list'
  const keys = new Set()
  for (const stage of work) {
    if (!stage || typeof stage !== 'object') return 'a stage is not an object'
    if (typeof stage.key !== 'string' || !STAGE_KEY.test(stage.key)) return `invalid stage key ${JSON.stringify(stage.key)}`
    if (RESERVED_STAGE_KEYS.includes(stage.key)) return `reserved stage key ${stage.key}`
    if (keys.has(stage.key)) return `duplicate stage key ${stage.key}`
    keys.add(stage.key)
    if (typeof stage.label !== 'string' || !stage.label.trim()) return `stage ${stage.key} has no label`
    if (typeof stage.retired !== 'boolean' || typeof stage.interview !== 'boolean') {
      return `stage ${stage.key} needs retired and interview as true or false`
    }
  }
  if (settings.changes !== undefined && !Array.isArray(settings.changes)) return 'changes must be a list'
  return null
}

export function workStages(settings) {
  return settings.stages.work
}

export function activeStages(settings) {
  return workStages(settings).filter((s) => !s.retired)
}

export function retiredStages(settings) {
  return workStages(settings).filter((s) => s.retired)
}

/** Keys a stage change may name: `applied` and the active work stages. */
export function selectableStageKeys(settings) {
  return [FIRST_STAGE, ...activeStages(settings).map((s) => s.key)]
}

/** Keys the move route accepts: the selectable stages and the two closed columns. */
export function moveTargets(settings) {
  return [...selectableStageKeys(settings), ...CLOSED_COLUMNS]
}

/** The name shown for a key: fixed, active or retired. An unknown key falls back to itself. */
export function labelFor(key, settings) {
  if (FIXED_LABELS[key]) return FIXED_LABELS[key]
  return workStages(settings).find((s) => s.key === key)?.label ?? key
}

/**
 * Where a folded application sits on the board:
 * `null` voided; `rejected` / `ghosted`; `closed` (the Closed panel, grouped by `folded.outcome`);
 * the stage key; or `unfiled` for a retired or unknown stage.
 */
export function boardColumn(folded, settings) {
  if (folded.voided) return null
  if (CLOSED_COLUMNS.includes(folded.outcome)) return folded.outcome
  if (folded.outcome) return 'closed'
  return selectableStageKeys(settings).includes(folded.stage) ? folded.stage : UNFILED
}

// --- operations ------------------------------------------------------------------------------

function cleanLabel(value) {
  const label = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''
  if (!label) throw new RegistryError(400, 'A stage needs a label')
  if (label.length > MAX_STAGE_LABEL) throw new RegistryError(400, `A label is at most ${MAX_STAGE_LABEL} characters`)
  return label
}

const sameLabel = (a, b) => a.toLocaleLowerCase() === b.toLocaleLowerCase()

/** The key a new stage gets: the label slugged with `_`, suffixed `_2`, `_3` ... while taken. */
export function keyForLabel(label, settings) {
  const base = label
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 36)
    .replace(/_+$/g, '') || 'stage'
  const taken = new Set([...RESERVED_STAGE_KEYS, ...workStages(settings).map((s) => s.key)])
  let key = base
  for (let n = 2; taken.has(key); n += 1) key = `${base}_${n}`
  return key
}

function requireWorkStage(settings, key) {
  if (RESERVED_STAGE_KEYS.includes(key)) throw new RegistryError(400, `${key} is a fixed stage`)
  const stage = workStages(settings).find((s) => s.key === key)
  if (!stage) throw new RegistryError(404, `Unknown stage ${JSON.stringify(key)}`)
  return stage
}

function requireUniqueLabel(settings, label, exceptKey) {
  const clash = activeStages(settings).find((s) => s.key !== exceptKey && sameLabel(s.label, label))
  if (clash) throw new RegistryError(409, `A stage labelled "${clash.label}" already exists`, { key: clash.key })
}

function optionalFlag(value) {
  if (value === undefined) return undefined
  if (typeof value !== 'boolean') throw new RegistryError(400, 'interview must be true or false')
  return value
}

/**
 * Apply one registry operation to `settings`. Returns { work, change } where `work` is the new
 * ordered list and `change` the entry for the settings log, or `change: null` when nothing changes
 * (a move at an edge). `openCount(key)` is the number of open, non-voided applications whose folded
 * stage is `key`; the caller supplies it under the store lock.
 */
export function applyStageOperation(settings, op, openCount = () => 0) {
  const work = workStages(settings).map((s) => ({ ...s }))
  const next = { ...settings, stages: { work } }
  const find = (key) => work.find((s) => s.key === key)

  switch (op.op) {
    case 'add': {
      const label = cleanLabel(op.label)
      const retired = retiredStages(settings).find((s) => sameLabel(s.label, label))
      if (retired) {
        throw new RegistryError(409, `"${retired.label}" is a retired stage; restore it instead`, { retiredKey: retired.key })
      }
      requireUniqueLabel(settings, label)
      if (activeStages(settings).length >= MAX_ACTIVE_WORK_STAGES) {
        throw new RegistryError(400, `At most ${MAX_ACTIVE_WORK_STAGES} work stages`)
      }
      const key = keyForLabel(label, settings)
      work.push({ key, label, retired: false, interview: optionalFlag(op.interview) ?? false })
      return { settings: next, change: { action: 'add', key, old: null, new: label } }
    }
    case 'rename': {
      const stage = requireWorkStage(settings, op.key)
      if (stage.retired) throw new RegistryError(400, 'Restore a retired stage before renaming it')
      const interview = optionalFlag(op.interview)
      if (op.label === undefined && interview === undefined) {
        throw new RegistryError(400, 'rename needs a label or an interview flag')
      }
      const label = op.label === undefined ? stage.label : cleanLabel(op.label)
      requireUniqueLabel(settings, label, stage.key)
      const target = find(stage.key)
      const before = { label: stage.label, interview: stage.interview }
      target.label = label
      if (interview !== undefined) target.interview = interview
      if (target.label === before.label && target.interview === before.interview) return { settings, change: null }
      return {
        settings: next,
        change: target.label !== before.label
          ? { action: 'rename', key: stage.key, old: before.label, new: label }
          : { action: 'interview', key: stage.key, old: before.interview, new: target.interview },
      }
    }
    case 'move': {
      const stage = requireWorkStage(settings, op.key)
      if (stage.retired) throw new RegistryError(400, 'A retired stage has no place on the board')
      if (op.dir !== 'up' && op.dir !== 'down') throw new RegistryError(400, 'dir must be up or down')
      const at = work.findIndex((s) => s.key === stage.key)
      const step = op.dir === 'up' ? -1 : 1
      let other = at + step
      while (work[other]?.retired) other += step
      if (!work[other]) return { settings, change: null }
      ;[work[at], work[other]] = [work[other], work[at]]
      return { settings: next, change: { action: 'move', key: stage.key, old: op.dir === 'up' ? 'down' : 'up', new: op.dir } }
    }
    case 'retire': {
      const stage = requireWorkStage(settings, op.key)
      if (stage.retired) throw new RegistryError(400, 'The stage is already retired')
      if (activeStages(settings).length <= 1) throw new RegistryError(400, 'The last work stage cannot be retired')
      const count = openCount(stage.key)
      if (count > 0) {
        throw new RegistryError(409, `Move the ${count} application${count === 1 ? '' : 's'} out first`, { count })
      }
      find(stage.key).retired = true
      return { settings: next, change: { action: 'retire', key: stage.key, old: stage.label, new: null } }
    }
    case 'unretire': {
      const stage = requireWorkStage(settings, op.key)
      if (!stage.retired) throw new RegistryError(400, 'The stage is not retired')
      if (activeStages(settings).length >= MAX_ACTIVE_WORK_STAGES) {
        throw new RegistryError(400, `At most ${MAX_ACTIVE_WORK_STAGES} work stages`)
      }
      requireUniqueLabel(settings, stage.label, stage.key)
      work.splice(work.findIndex((s) => s.key === stage.key), 1)
      work.push({ ...stage, retired: false })
      return { settings: next, change: { action: 'unretire', key: stage.key, old: null, new: stage.label } }
    }
    default:
      throw new RegistryError(400, 'op must be add, rename, move, retire or unretire')
  }
}

/** The settings with `change` logged (last MAX_CHANGES kept) and `updatedAt` bumped. */
export function withChange(settings, change, at) {
  return {
    ...settings,
    updatedAt: at,
    changes: [...(settings.changes ?? []), { at, ...change }].slice(-MAX_CHANGES),
  }
}

/**
 * Merge a backup's settings into the current ones (3.1 step 5): the current switches, labels and
 * order win; a key found only in the backup is appended as retired with its label.
 * Returns { settings, added } with `added` the keys appended.
 */
export function mergeBackupSettings(current, backup, at) {
  const have = new Set(workStages(current).map((s) => s.key))
  const added = workStages(backup).filter((s) => !have.has(s.key)).map((s) => s.key)
  if (!added.length) return { settings: current, added }
  const extra = workStages(backup).filter((s) => added.includes(s.key)).map((s) => ({ ...s, retired: true }))
  let merged = { ...current, stages: { work: [...workStages(current), ...extra] } }
  for (const stage of extra) merged = withChange(merged, { action: 'restore', key: stage.key, old: null, new: stage.label }, at)
  return { settings: merged, added }
}
