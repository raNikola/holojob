// What applying a reviewed draft would do, worked out without touching anything: the confirm screen reads it, and the cache impact
// request is made from `planned`. Pure; it calls the same applyImportDraft the apply step calls, so the preview cannot disagree with the result.

import { BASIC_FIELDS, SECTIONS, applyImportDraft, effectiveSectionChoice, liveSummary, resolveChoices, sectionKeys, willBeActive } from './importDraft.js'
import { sameProfile } from './importApply.js'

const text = (v) => (typeof v === 'string' ? v.trim() : '')

/**
 * @returns {{
 *   planned: object, unchanged: boolean, becomesActive: boolean,
 *   sections: { id: string, label: string, choice: string, added: number, removed: number, kept: number }[],
 *   basics: { field: string, action: 'fills'|'changes' }[], summary: 'fills'|'changes'|null,
 *   removals: number, needsReplaceConfirm: boolean,
 * }}
 */
export function buildImportPreview(profile, draft, choices, options = {}) {
  const resolved = resolveChoices(profile, draft, choices)
  const planned = applyImportDraft(profile, draft, resolved, options)

  const sections = SECTIONS.map(({ id, label }) => {
    const before = sectionKeys(profile, id)
    const after = sectionKeys(planned, id)
    const had = new Set(before)
    const has = new Set(after)
    return {
      id,
      label,
      choice: effectiveSectionChoice(profile, id, resolved.sections?.[id]),
      added: [...has].filter((k) => !had.has(k)).length,
      removed: [...had].filter((k) => !has.has(k)).length,
      kept: [...had].filter((k) => has.has(k)).length,
    }
  })

  const basics = BASIC_FIELDS.flatMap((field) => {
    const was = text(profile.basicProfile?.[field])
    const now = text(planned.basicProfile?.[field])
    if (was === now) return []
    return [{ field, action: was ? 'changes' : 'fills' }]
  })

  const wasSummary = liveSummary(profile)
  const nowSummary = liveSummary(planned)
  const summary = wasSummary === nowSummary ? null : wasSummary ? 'changes' : 'fills'

  const removals = sections.filter((s) => s.choice === 'replace').reduce((n, s) => n + s.removed, 0)
  return {
    planned,
    unchanged: sameProfile(planned, profile),
    becomesActive: willBeActive(profile),
    sections,
    basics,
    summary,
    removals,
    needsReplaceConfirm: removals > 0,
  }
}
