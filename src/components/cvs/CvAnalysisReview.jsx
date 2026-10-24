import { useMemo, useState } from 'react'
import { AlertTriangle, Check, Loader2 } from 'lucide-react'
import Button from '../ui/Button'
import { buildSuggestions, defaultSelection, usableIds } from '../../utils/cvAnalysis'

function StatusTag({ status, applied }) {
  if (applied) {
    return (
      <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
        <Check className="h-3 w-3" /> Applied
      </span>
    )
  }
  if (status === 'have') return <span className="ml-2 text-xs text-stone-500">Already in your profile</span>
  if (status === 'differs') {
    return (
      <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
        <AlertTriangle className="h-3 w-3" /> Differs from your profile, review
      </span>
    )
  }
  return null
}

function Row({ id, selected, toggle, status, applied, children, disabled, nested }) {
  const off = disabled || status === 'have'
  const differs = status === 'differs'
  return (
    <li className={`flex items-start gap-2 py-1.5 ${differs ? 'my-1 rounded-md border border-amber-300 bg-amber-50/70 px-2 dark:border-amber-700 dark:bg-amber-950/30' : ''}`}>
      <input
        type="checkbox"
        id={id}
        checked={applied || selected.has(id)}
        disabled={off}
        onChange={() => toggle(id)}
        className="mt-1 h-4 w-4 shrink-0 accent-teal-600"
      />
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className={`block text-sm ${off && !applied ? 'text-stone-500' : 'text-stone-800 dark:text-stone-200'}`}>
          {children}
          <StatusTag status={status} applied={applied} />
        </label>
        {/* Outside the label, so opening the bullets does not tick the role. */}
        {nested}
      </div>
    </li>
  )
}

function Section({ title, hint, children }) {
  return (
    <section className="border-t border-stone-100 pt-3 dark:border-stone-800">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-500">{title}</h4>
      {hint && <p className="mt-0.5 text-xs text-stone-500">{hint}</p>}
      {children}
    </section>
  )
}

function Groups({ label, group, id, selected, toggle, disabled, applied }) {
  if (group.status === 'none') return null
  return (
    <Section title={label} hint="The CV's own groups, kept as written.">
      <ul>
        <Row id={id} selected={selected} toggle={toggle} status={group.status} applied={applied} disabled={disabled}>
          Use {group.next.length} groups{group.current.length ? ` (replaces ${group.current.length} saved)` : ''}
        </Row>
      </ul>
      <div className="ml-6 space-y-1.5">
        {group.next.map((g) => (
          <p key={g.label} className="text-sm text-stone-700 dark:text-stone-300">
            <span className="font-medium">{g.label}:</span> {g.items.join(', ')}
          </p>
        ))}
      </div>
    </Section>
  )
}

/** The suggestions from one analysis. Nothing is written until Apply. */
export default function CvAnalysisReview({ profile, cv, isDefault, onApply, onRetrySync }) {
  const facts = cv.analysis.facts
  const s = useMemo(() => buildSuggestions(profile, facts), [profile, facts])
  const [selected, setSelected] = useState(() => defaultSelection(buildSuggestions(profile, facts)))
  const [working, setWorking] = useState(false)
  const appliedIds = useMemo(() => new Set(cv.analysis.applied || []), [cv.analysis.applied])
  const isApplied = (id, status) => status === 'have' && appliedIds.has(id)
  const last = cv.analysis.lastApply

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const locked = !isDefault
  const usable = [...usableIds(s, selected)]
  const empty = !s.skills.length && !s.projects.length && !s.experience.length && !s.education.length && !s.certifications.length
    && s.competencyGroups.status === 'none' && s.toolGroups.status === 'none' && !s.summary

  const apply = async () => {
    setWorking(true)
    try { await onApply(new Set(usable)) } finally { setWorking(false) }
  }
  const retry = async () => {
    setWorking(true)
    try { await onRetrySync() } finally { setWorking(false) }
  }
  const allItems = [...s.skills, ...s.projects, ...s.experience, ...s.education, ...s.certifications]
  const differing = [...allItems.filter((i) => i.status === 'differs'), ...(s.summary?.status === 'differs' ? [s.summary] : []),
    ...[s.competencyGroups, s.toolGroups].filter((g) => g.status === 'differs')]

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-stone-200 bg-stone-50/60 p-4 dark:border-stone-700 dark:bg-stone-900/40" data-testid="cv-analysis-review">
      <p className="text-xs text-stone-500">
        Read by {cv.analysis.provider}{cv.analysis.model ? ` (${cv.analysis.model})` : ''} on {new Date(cv.analysis.analyzedAt).toLocaleString()}.
        Every item below was found in the CV text. Tick what you want in your profile; nothing is changed until you press Apply.
      </p>
      {locked && <p className="text-xs text-amber-700 dark:text-amber-400">This is not your default CV. Set it as default to apply its suggestions.</p>}
      {working && (
        <p role="status" className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-300">
          <Loader2 className="h-4 w-4 animate-spin" /> Applying to your profile and regenerating intelligence…
        </p>
      )}
      {!working && last?.state === 'synced' && (
        <p role="status" data-testid="apply-result" className="flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200">
          <Check className="h-4 w-4 shrink-0" />
          Applied and synced: {last.count} {last.count === 1 ? 'item' : 'items'} updated, intelligence regenerated ({new Date(last.at).toLocaleTimeString()}).
        </p>
      )}
      {!working && last?.state === 'failed' && (
        <div role="alert" data-testid="apply-result" className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/30 dark:text-red-200">
          <p>Applied {last.count} {last.count === 1 ? 'item' : 'items'} to your profile, but intelligence was not regenerated, so scoring still uses the old one.</p>
          <p className="mt-1 text-xs">{last.error}</p>
          <Button variant="secondary" className="mt-2" onClick={retry}>Regenerate now</Button>
        </div>
      )}
      {!working && differing.length > 0 && !locked && (
        <p className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {differing.length} {differing.length === 1 ? 'suggestion differs' : 'suggestions differ'} from what is in your profile. They are not ticked: check each one and tick it to replace yours.
        </p>
      )}
      {empty && <p className="text-sm text-stone-600">The analysis found nothing it could confirm in the CV text.</p>}

      {s.skills.length > 0 && (
        <Section title={`Skills (${s.skills.filter((i) => i.status === 'new').length} new)`}>
          <ul className="grid gap-x-4 sm:grid-cols-2">
            {s.skills.map((i) => <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} applied={isApplied(i.id, i.status)} disabled={locked}>{i.value}</Row>)}
          </ul>
        </Section>
      )}

      {s.experience.length > 0 && (
        <Section title="Work experience" hint="Saved as structured roles with their bullets. A role your profile lacks is also added to its work-experience list.">
          <ul>
            {s.experience.map((i) => (
              <Row
                key={i.id}
                id={i.id}
                selected={selected}
                toggle={toggle}
                status={i.status}
                applied={isApplied(i.id, i.status)}
                disabled={locked}
                nested={i.role.bullets.length > 0 && (
                  <details className="mt-0.5 text-sm" data-testid={`bullets-${i.id}`}>
                    <summary className="cursor-pointer text-xs text-stone-500">Show {i.role.bullets.length} bullets</summary>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-stone-700 dark:text-stone-300">
                      {i.role.bullets.map((b) => <li key={b}>{b}</li>)}
                    </ul>
                  </details>
                )}
              >
                <span className="font-medium">{i.label}</span>
                <span className="ml-2 text-xs text-stone-500">{i.role.bullets.length} bullets</span>
              </Row>
            ))}
          </ul>
        </Section>
      )}

      <Groups label="Core competencies" group={s.competencyGroups} id="competencyGroups" selected={selected} toggle={toggle} disabled={locked} applied={isApplied('competencyGroups', s.competencyGroups.status)} />
      <Groups label="Tools" group={s.toolGroups} id="toolGroups" selected={selected} toggle={toggle} disabled={locked} applied={isApplied('toolGroups', s.toolGroups.status)} />

      {s.education.length > 0 && (
        <Section title="Education" hint="Checked against your profile. A different entry replaces yours only if you tick it.">
          <ul>
            {s.education.map((i) => (
              <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} applied={isApplied(i.id, i.status)} disabled={locked}>
                {i.value}
                {i.status === 'differs' && <span className="block text-xs text-stone-600 dark:text-stone-400">Your profile: {i.existing}</span>}
                {i.existingCutOff && (
                  <span className="block text-xs font-medium text-amber-800 dark:text-amber-300">
                    Your entry starts with “{i.existing.slice(0, 4)}” and looks cut off; the CV's version is probably the right one. Tick it to replace yours.
                  </span>
                )}
              </Row>
            ))}
          </ul>
        </Section>
      )}

      {s.certifications.length > 0 && (
        <Section title="Certifications">
          <ul>
            {s.certifications.map((i) => (
              <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} applied={isApplied(i.id, i.status)} disabled={locked}>
                {i.value}
                {i.status === 'differs' && <span className="block text-xs text-stone-500">Your profile: {i.existing}</span>}
              </Row>
            ))}
          </ul>
        </Section>
      )}

      {s.projects.length > 0 && (
        <Section title="Key projects (Questionnaire: projects you are proud of)" hint="Added to your answer to question 4, which keeps what it already has.">
          <ul>
            {s.projects.map((i) => <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} applied={isApplied(i.id, i.status)} disabled={locked}>{i.value}</Row>)}
          </ul>
        </Section>
      )}

      {s.summary && (
        <Section title="Career summary (Questionnaire: question 17)" hint="A draft the model wrote from facts in the CV. It replaces your current answer only if you tick it.">
          <ul>
            <Row id="summary" selected={selected} toggle={toggle} status={s.summary.status} applied={isApplied('summary', s.summary.status)} disabled={locked}>
              <span className="whitespace-pre-line">{s.summary.draft}</span>
              {s.summary.status === 'differs' && <span className="mt-1 block text-xs text-stone-500">Your current answer: {s.summary.existing}</span>}
            </Row>
          </ul>
        </Section>
      )}

      {cv.analysis.rejected?.length > 0 && (
        <details className="border-t border-stone-100 pt-3 dark:border-stone-800">
          <summary className="cursor-pointer text-xs text-stone-500">{cv.analysis.rejected.length} items dropped because they were not found in the CV</summary>
          <ul className="mt-1 space-y-1 text-xs text-stone-500">
            {cv.analysis.rejected.map((r, i) => <li key={`${r.field}-${i}`}><span className="font-medium">{r.field}:</span> {r.value} — {r.reason}</li>)}
          </ul>
        </details>
      )}

      <div className="flex items-center gap-3 border-t border-stone-100 pt-3 dark:border-stone-800">
        <Button onClick={apply} disabled={locked || working || usable.length === 0}>Apply selected ({usable.length})</Button>
      </div>
    </div>
  )
}
