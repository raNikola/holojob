/**
 * The Phase 1 engine's output in shadow mode (ENGINE_CONTRACT.md section 7):
 * job.engineShadow, written by run_scoring.py when HOLOJOB_ENGINE_SHADOW is
 * on. Display only: nothing here feeds matchScore, sorting or filters.
 */

export const ENGINE_LABEL_VARIANT = {
  Strong: 'high',
  Good: 'default',
  Partial: 'medium',
  Weak: 'warn',
  Incomplete: 'low',
}

export const BUCKET = {
  apply: { label: 'apply', variant: 'high' },
  check_first: { label: 'check first', variant: 'medium' },
  blocked: { label: 'blocked', variant: 'warn' },
}

export const STATUS = {
  MET: { mark: '✓', className: 'text-emerald-700 dark:text-emerald-400' },
  PARTIAL: { mark: '◐', className: 'text-amber-700 dark:text-amber-400' },
  CONTRADICTED: { mark: '✗', className: 'text-red-700 dark:text-red-400' },
  // Nothing in the profile speaks for it: not held against the candidate (engine 0.3.0). Rows stored by 0.2.x say MISSING for the same thing.
  NOT_EVIDENCED: { mark: '–', className: 'text-stone-500' },
  MISSING: { mark: '–', className: 'text-stone-500' },
  UNKNOWN: { mark: '?', className: 'text-stone-500' },
}

export const GATE_RESULT = {
  pass: { mark: '✓', className: 'text-emerald-700 dark:text-emerald-400' },
  unknown: { mark: '?', className: 'text-amber-700 dark:text-amber-400' },
  fail: { mark: '✗', className: 'text-red-700 dark:text-red-400' },
}

// Evidence strength 0-4 (contract section 4.3).
export const STRENGTH = ['none', 'claim', 'contextual', 'demonstrated', 'with outcome']

export const GATE_NAME = {
  work_authorization: 'Work authorization',
  location: 'Location',
  language: 'Language',
  salary_floor: 'Salary floor',
  role_family: 'Role family',
}

/** An engine output with a Fit, as opposed to none or a failed call. */
export function hasEngineResult(shadow) {
  return Boolean(shadow && !shadow.error && typeof shadow.fit === 'number')
}

/** One line for a tooltip: "Good · Fit 56 · confidence 0.88 · apply · 5/7 musts met". */
export function engineSummary(shadow) {
  if (!shadow) return ''
  if (shadow.error) return `New engine (shadow): call failed: ${shadow.error}`
  const c = shadow.counts || {}
  const parts = [
    shadow.labelText || shadow.label,
    `Fit ${shadow.fit}`,
    `confidence ${Number(shadow.confidence).toFixed(2)}`,
    BUCKET[shadow.bucket]?.label || shadow.bucket,
  ]
  if (c.mustTotal) parts.push(`${c.mustMet}/${c.mustTotal} musts met`)
  if (c.unknown) parts.push(`${c.unknown} unknown`)
  if (shadow.caps?.length) parts.push(`capped: ${shadow.caps.join(', ')}`)
  return `New engine (shadow): ${parts.join(' · ')}`
}

export const QUOTE_NOT_VERIFIED_NOTE = 'Evidence found, quote not verified'

// verify.py apply_proposal writes: "requirement 'ID': PARTIAL lowered to UNKNOWN, evidence quote ... not found in ...". Read-only: the stored answer is not changed.
const LOWERED_WARNING = /^requirement (?:'([^']*)'|"([^"]*)"): (?:MET|PARTIAL) lowered to (?:PARTIAL|UNKNOWN), evidence quote /

/** The ids of the requirements whose status the quote check lowered, read from the stored answer's warnings. */
export function quoteLoweredIds(shadow) {
  const ids = new Set()
  for (const w of shadow?.warnings || []) {
    const m = typeof w === 'string' ? LOWERED_WARNING.exec(w) : null
    if (m) ids.add(m[1] ?? m[2])
  }
  return ids
}
