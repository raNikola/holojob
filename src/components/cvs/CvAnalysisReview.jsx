import { useMemo, useState } from 'react'
import { Check } from 'lucide-react'
import Button from '../ui/Button'
import { buildSuggestions, defaultSelection } from '../../utils/cvAnalysis'

const STATUS_LABEL = { new: 'New', have: 'Already in your profile', differs: 'Differs from your profile' }

function Row({ id, selected, toggle, status, children, disabled, nested }) {
  const off = disabled || status === 'have'
  return (
    <li className="flex items-start gap-2 py-1.5">
      <input
        type="checkbox"
        id={id}
        checked={selected.has(id)}
        disabled={off}
        onChange={() => toggle(id)}
        className="mt-1 h-4 w-4 shrink-0 accent-teal-600"
      />
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className={`block text-sm ${off ? 'text-stone-500' : 'text-stone-800 dark:text-stone-200'}`}>
          {children}
          {status !== 'new' && (
            <span className={`ml-2 text-xs ${status === 'differs' ? 'text-amber-700 dark:text-amber-400' : 'text-stone-500'}`}>{STATUS_LABEL[status]}</span>
          )}
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

function Groups({ label, group, id, selected, toggle, disabled }) {
  if (group.status === 'none') return null
  return (
    <Section title={label} hint="The CV's own groups, kept as written.">
      <ul>
        <Row id={id} selected={selected} toggle={toggle} status={group.status} disabled={disabled}>
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
export default function CvAnalysisReview({ profile, cv, isDefault, onApply }) {
  const facts = cv.analysis.facts
  const s = useMemo(() => buildSuggestions(profile, facts), [profile, facts])
  const [selected, setSelected] = useState(() => defaultSelection(buildSuggestions(profile, facts)))
  const [applied, setApplied] = useState(false)

  const toggle = (id) => {
    setApplied(false)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const locked = !isDefault
  const usable = [...selected].filter((id) => {
    const all = [...s.skills, ...s.projects, ...s.experience, ...s.education, ...s.certifications]
    const item = all.find((i) => i.id === id)
    return item ? item.status !== 'have' : true
  })
  const empty = !s.skills.length && !s.projects.length && !s.experience.length && !s.education.length && !s.certifications.length
    && s.competencyGroups.status === 'none' && s.toolGroups.status === 'none' && !s.summary

  const apply = () => { onApply(new Set(usable)); setApplied(true) }

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-stone-200 bg-stone-50/60 p-4 dark:border-stone-700 dark:bg-stone-900/40" data-testid="cv-analysis-review">
      <p className="text-xs text-stone-500">
        Read by {cv.analysis.provider}{cv.analysis.model ? ` (${cv.analysis.model})` : ''} on {new Date(cv.analysis.analyzedAt).toLocaleString()}.
        Every item below was found in the CV text. Tick what you want in your profile; nothing is changed until you press Apply.
      </p>
      {locked && <p className="text-xs text-amber-700 dark:text-amber-400">This is not your default CV. Set it as default to apply its suggestions.</p>}
      {empty && <p className="text-sm text-stone-600">The analysis found nothing it could confirm in the CV text.</p>}

      {s.skills.length > 0 && (
        <Section title={`Skills (${s.skills.filter((i) => i.status === 'new').length} new)`}>
          <ul className="grid gap-x-4 sm:grid-cols-2">
            {s.skills.map((i) => <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} disabled={locked}>{i.value}</Row>)}
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

      <Groups label="Core competencies" group={s.competencyGroups} id="competencyGroups" selected={selected} toggle={toggle} disabled={locked} />
      <Groups label="Tools" group={s.toolGroups} id="toolGroups" selected={selected} toggle={toggle} disabled={locked} />

      {s.education.length > 0 && (
        <Section title="Education" hint="Checked against your profile. A different entry replaces yours only if you tick it.">
          <ul>
            {s.education.map((i) => (
              <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} disabled={locked}>
                {i.value}
                {i.status === 'differs' && <span className="block text-xs text-stone-500">Your profile: {i.existing}</span>}
              </Row>
            ))}
          </ul>
        </Section>
      )}

      {s.certifications.length > 0 && (
        <Section title="Certifications">
          <ul>
            {s.certifications.map((i) => (
              <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} disabled={locked}>
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
            {s.projects.map((i) => <Row key={i.id} id={i.id} selected={selected} toggle={toggle} status={i.status} disabled={locked}>{i.value}</Row>)}
          </ul>
        </Section>
      )}

      {s.summary && (
        <Section title="Career summary (Questionnaire: question 17)" hint="A draft the model wrote from facts in the CV. It replaces your current answer only if you tick it.">
          <ul>
            <Row id="summary" selected={selected} toggle={toggle} status={s.summary.status} disabled={locked}>
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
        <Button onClick={apply} disabled={locked || usable.length === 0}>Apply selected ({usable.length})</Button>
        {applied && <span className="inline-flex items-center gap-1 text-sm text-teal-700 dark:text-teal-300"><Check className="h-4 w-4" /> Applied</span>}
      </div>
    </div>
  )
}
