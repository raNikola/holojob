import { useState } from 'react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'

const BASIC_LABELS = { fullName: 'Full name', email: 'Email', phone: 'Phone', location: 'Location', currentRole: 'Current role', experienceYears: 'Experience (years)' }
const CHOICE_WORDS = { add: 'Added to current', replace: 'Replaces current', keep: 'Current kept' }

function SectionLine({ section }) {
  const parts = []
  if (section.added) parts.push(`${section.added} added`)
  if (section.removed) parts.push(`${section.removed} removed`)
  if (section.kept) parts.push(`${section.kept} kept`)
  return (
    <li className="flex flex-wrap justify-between gap-2 text-sm">
      <span className="font-medium text-stone-800 dark:text-stone-200">{section.label}</span>
      <span className="text-stone-600 dark:text-stone-400">{CHOICE_WORDS[section.choice] || 'Current kept'}: {parts.length ? parts.join(', ') : 'no change'}</span>
    </li>
  )
}

/** Plain sentences about the caches that depend on the profile. Counts only; nothing here comes from the profile's text. */
export function impactLines(impact) {
  const lines = []
  const { profileVersion, evidence, matcher, findings } = impact
  if (!profileVersion.changed) {
    lines.push('Matching evidence is unchanged: every cached matcher answer stays valid, and nothing is asked again.')
  } else {
    lines.push(`Matching evidence changes (${evidence.added} added, ${evidence.removed} removed). ${matcher.stopMatching} cached matcher answer${matcher.stopMatching === 1 ? '' : 's'} will no longer match, so those jobs are asked again the next time you run a judged scoring run, which costs AI budget. The old answers are kept: Undo, or restoring the backup, makes them match again.`)
  }
  lines.push('The fit judge cache is not affected until you regenerate your intelligence.')
  if (findings.mayMiss && findings.stored > 0) lines.push(`${findings.stored} stored job analysis${findings.stored === 1 ? '' : 'es'} may be asked again when you reopen them, because the profile summary they use changes.`)
  lines.push('Nothing is re-run by the import itself.')
  return lines
}

/** Step between the review and the write: what will change, the backup, the cache impact, and the second confirm for Replace. */
export default function ImportConfirm({ preview, impact, applying, error, onApply, onBack }) {
  const [understood, setUnderstood] = useState(false)
  const blocked = preview.needsReplaceConfirm && !understood
  const changedSections = preview.sections.filter((s) => s.added || s.removed || s.choice === 'replace')

  return (
    <div className="space-y-4">
      <Alert variant="info" title="Confirm the import">
        Nothing has been written yet. Applying makes a backup of your current profile first (the last 10 import backups are kept on the server); if the backup fails, nothing changes.
      </Alert>

      <Card title="What will change">
        {preview.basics.length === 0 && !preview.summary && changedSections.length === 0 ? (
          <p className="text-sm text-stone-600 dark:text-stone-400">Your profile fields stay as they are. Only a new CV entry is added to My CVs.</p>
        ) : (
          <ul className="space-y-2">
            {preview.basics.map((b) => (
              <li key={b.field} className="flex flex-wrap justify-between gap-2 text-sm">
                <span className="font-medium text-stone-800 dark:text-stone-200">{BASIC_LABELS[b.field]}</span>
                <span className="text-stone-600 dark:text-stone-400">{b.action === 'fills' ? 'Filled in' : 'Replaced'}</span>
              </li>
            ))}
            {preview.summary && (
              <li className="flex flex-wrap justify-between gap-2 text-sm">
                <span className="font-medium text-stone-800 dark:text-stone-200">Summary</span>
                <span className="text-stone-600 dark:text-stone-400">{preview.summary === 'fills' ? 'Filled in' : 'Replaced'}</span>
              </li>
            )}
            {changedSections.map((s) => <SectionLine key={s.id} section={s} />)}
          </ul>
        )}
        <p className="mt-4 text-sm text-stone-600 dark:text-stone-400">
          A new entry is added to My CVs. {preview.becomesActive ? 'You have no CV yet, so it becomes your active CV.' : 'It does not become your active CV.'}
        </p>
      </Card>

      {preview.needsReplaceConfirm && (
        <Alert variant="error" title="Replace removes existing entries">
          <p>{preview.removals} existing entr{preview.removals === 1 ? 'y' : 'ies'} will be removed from your profile. The backup lets you get them back.</p>
          <label className="mt-2 flex items-start gap-2 text-sm">
            <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} className="mt-1" />
            <span>I understand that these entries will be removed.</span>
          </label>
        </Alert>
      )}

      <Card title="Effect on your scoring caches" description="Worked out on this server from your current profile and the one the import would produce.">
        {impact.status === 'loading' && <p className="text-sm text-stone-500">Working it out...</p>}
        {impact.status === 'failed' && <p className="text-sm text-stone-600 dark:text-stone-400">It could not be worked out. You can still apply; the import re-runs nothing by itself.</p>}
        {impact.status === 'ready' && <ul className="list-inside list-disc space-y-1 text-sm text-stone-700 dark:text-stone-300">{impactLines(impact.data).map((line) => <li key={line}>{line}</li>)}</ul>}
      </Card>

      {error && <Alert variant="error" title="Not applied">{error}</Alert>}

      <div className="flex flex-wrap justify-end gap-2 border-t border-stone-200 pt-4 dark:border-stone-800">
        <Button variant="ghost" onClick={onBack} disabled={applying}>Back to review</Button>
        <Button onClick={onApply} disabled={applying || blocked}>{applying ? 'Applying...' : 'Apply import'}</Button>
      </div>
    </div>
  )
}
