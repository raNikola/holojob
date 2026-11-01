import { Plus, Trash2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Badge from '../ui/Badge'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import { LANGUAGE_PROFICIENCIES } from '../../utils/languages'
import {
  BASIC_FIELDS,
  IMPORT_SOURCES,
  SECTIONS,
  addEntry,
  draftItems,
  effectiveBasicChoice,
  effectiveSectionChoice,
  effectiveSummaryChoice,
  liveCount,
  liveSummary,
  removeEntry,
  willBeActive,
  withBasic,
  withEntry,
  withSection,
  withSummary,
} from '../../modules/profile/importDraft'

const BASIC_LABELS = { fullName: 'Full name', email: 'Email', phone: 'Phone', location: 'Location', currentRole: 'Current role', experienceYears: 'Experience (years)' }
const LEVELS = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence', derived: 'Derived from the text' }
const selectClass = 'rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50'

function Confidence({ level }) {
  return level ? <Badge variant={level}>{LEVELS[level]}</Badge> : null
}

function LineList({ items, onChange, placeholder }) {
  const set = (index, value) => onChange(items.map((item, i) => (i === index ? value : item)))
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex gap-2">
          <input
            value={item}
            onChange={(e) => set(i, e.target.value)}
            placeholder={placeholder}
            className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
          />
          <button type="button" aria-label="Remove entry" onClick={() => onChange(items.filter((_, j) => j !== i))} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      <Button variant="ghost" onClick={() => onChange([...items, ''])}><Plus className="h-4 w-4" /> Add</Button>
    </div>
  )
}

function LanguageList({ items, onChange }) {
  const set = (index, patch) => onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex gap-2">
          <input
            value={item.language}
            onChange={(e) => set(i, { language: e.target.value })}
            placeholder="Language"
            className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
          />
          <select value={item.proficiency} onChange={(e) => set(i, { proficiency: e.target.value })} className={selectClass} aria-label="Level">
            <option value="">Level not stated</option>
            {LANGUAGE_PROFICIENCIES.map((level) => <option key={level} value={level}>{level}</option>)}
          </select>
          <button type="button" aria-label="Remove language" onClick={() => onChange(items.filter((_, j) => j !== i))} className="rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      <Button variant="ghost" onClick={() => onChange([...items, { language: '', proficiency: '' }])}><Plus className="h-4 w-4" /> Add</Button>
    </div>
  )
}

function ExperienceEntries({ draft, onDraftChange }) {
  const entries = draft.parsedData?.experienceDetail || []
  const change = (index, patch) => onDraftChange(withEntry(draft, index, { ...entries[index], ...patch }))
  return (
    <div className="space-y-4">
      {entries.map((entry, i) => (
        <div key={i} className="rounded-lg border border-stone-200 p-3 dark:border-stone-700">
          <div className="mb-2 flex items-center justify-between">
            <Confidence level={draft.confidence?.[`experienceDetail.${i}`]} />
            <button type="button" aria-label="Remove entry" onClick={() => onDraftChange(removeEntry(draft, i))} className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-red-500 dark:hover:bg-stone-800">
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Title" id={`exp-title-${i}`} value={entry.title} onChange={(e) => change(i, { title: e.target.value })} />
            <Input label="Company" id={`exp-company-${i}`} value={entry.company} onChange={(e) => change(i, { company: e.target.value })} />
            <Input label="Location" id={`exp-location-${i}`} value={entry.location || ''} onChange={(e) => change(i, { location: e.target.value })} />
            <Input label="Start" id={`exp-start-${i}`} value={entry.start} onChange={(e) => change(i, { start: e.target.value })} />
            <Input label="End" id={`exp-end-${i}`} value={entry.end} onChange={(e) => change(i, { end: e.target.value })} />
          </div>
          <Textarea
            className="mt-3"
            label="Description"
            id={`exp-description-${i}`}
            rows={3}
            value={entry.description || ''}
            onChange={(e) => change(i, { description: e.target.value })}
          />
          <Textarea
            className="mt-3"
            label="Bullets (one per line)"
            id={`exp-bullets-${i}`}
            rows={4}
            value={(entry.bullets || []).join('\n')}
            onChange={(e) => change(i, { bullets: e.target.value.split('\n') })}
          />
        </div>
      ))}
      <Button variant="ghost" onClick={() => onDraftChange(addEntry(draft))}><Plus className="h-4 w-4" /> Add an entry</Button>
    </div>
  )
}

function SectionBody({ id, draft, onDraftChange }) {
  const parsed = draft.parsedData || {}
  if (id === 'languages') return <LanguageList items={draft.languages || []} onChange={(items) => onDraftChange(withSection(draft, id, items))} />
  if (id === 'experience' && (parsed.experienceDetail?.length || !parsed.workExperience?.length)) {
    return <ExperienceEntries draft={draft} onDraftChange={onDraftChange} />
  }
  return <LineList items={draftItems(draft, id)} placeholder="Entry" onChange={(items) => onDraftChange(withSection(draft, id, items))} />
}

function SummaryCard({ draft, profile, choice, onDraftChange, onChoice }) {
  const current = liveSummary(profile)
  const edited = Boolean(profile._editedFields?.summary)
  const value = draft.summary || ''
  return (
    <Card
      title="Summary"
      description={current ? 'Your profile already has a summary.' : 'Your profile has no summary yet.'}
      action={(
        <div className="flex items-center gap-2">
          <Confidence level={draft.confidence?.summary} />
          {value && !edited && (
            <select value={choice} onChange={(e) => onChoice(e.target.value)} className={selectClass} aria-label="Summary: what to do">
              <option value="use">{current ? 'Replace current' : 'Fill'}</option>
              <option value="keep">Keep current</option>
            </select>
          )}
        </div>
      )}
    >
      <Textarea
        label="Summary text"
        id="import-summary"
        rows={4}
        value={value}
        onChange={(e) => onDraftChange(withSummary(draft, e.target.value))}
      />
      {current && value && !edited && <p className="mt-2 text-xs text-stone-500">Current: {current}</p>}
    </Card>
  )
}

export default function ImportReview({ draft, profile, choices, onDraftChange, onChoicesChange, onSave, onDiscard, saving = false }) {
  const source = IMPORT_SOURCES[draft.source] || { name: 'Imported text' }
  const setBasicChoice = (field, value) => onChoicesChange({ ...choices, basics: { ...choices.basics, [field]: value } })
  const setSummaryChoice = (value) => onChoicesChange({ ...choices, summary: value })
  const setSectionChoice = (id, value) => onChoicesChange({ ...choices, sections: { ...choices.sections, [id]: value } })

  return (
    <div className="space-y-4">
      <Alert variant="info" title="Review before saving">
        Nothing has been saved yet. Correct anything below, then choose what to do with each part. {draft.rawText ? `The full text (${draft.rawText.length.toLocaleString()} characters) is kept with the saved CV.` : ''}
      </Alert>
      {draft.warnings?.length > 0 && (
        <Alert variant="info" title="Notes from reading the text">
          <ul className="list-inside list-disc">{draft.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Alert>
      )}

      <Card title="Basics" description="Contact details are kept in their own fields only.">
        <div className="space-y-4">
          {BASIC_FIELDS.map((field) => {
            const current = profile.basicProfile?.[field] || ''
            const edited = Boolean(profile._editedFields?.[field])
            const value = draft.basicProfile?.[field] || ''
            const choice = effectiveBasicChoice(profile, field, choices.basics?.[field])
            return (
              <div key={field} className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
                <Input
                  label={BASIC_LABELS[field]}
                  id={`basic-${field}`}
                  value={value}
                  onChange={(e) => onDraftChange(withBasic(draft, field, e.target.value))}
                  confidenceTag={<Confidence level={draft.confidence?.[field]} />}
                />
                {value && (
                  <div className="text-xs text-stone-500">
                    {edited ? (
                      <span>You edited this field; it stays as it is.</span>
                    ) : (
                      <select value={choice} onChange={(e) => setBasicChoice(field, e.target.value)} className={selectClass} aria-label={`${BASIC_LABELS[field]}: what to do`}>
                        <option value="use">{current ? 'Replace current' : 'Fill'}</option>
                        <option value="keep">Keep current</option>
                      </select>
                    )}
                    {current && !edited && <span className="ml-2">Current: {current}</span>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {draft.headline && <p className="mt-4 text-xs text-stone-500 dark:text-stone-400">Headline in the document: "{draft.headline}". Target roles are not guessed from a CV; you choose them in your profile.</p>}
      </Card>

      <SummaryCard draft={draft} profile={profile} choice={effectiveSummaryChoice(profile, choices.summary)} onDraftChange={onDraftChange} onChoice={setSummaryChoice} />

      {SECTIONS.map(({ id, label, editedKey }) => {
        const count = draftItems(draft, id).length
        const edited = Boolean(profile._editedFields?.[editedKey])
        const choice = effectiveSectionChoice(profile, id, choices.sections?.[id])
        const currentCount = liveCount(profile, id)
        return (
          <Card
            key={id}
            title={`${label} (${count})`}
            action={(
              <div className="flex items-center gap-2">
                <Confidence level={draft.confidence?.[editedKey]} />
                <select value={choice} onChange={(e) => setSectionChoice(id, e.target.value)} className={selectClass} aria-label={`${label}: what to do`}>
                  <option value="add">Add to current</option>
                  <option value="replace" disabled={edited}>Replace current</option>
                  <option value="keep">Keep current</option>
                </select>
              </div>
            )}
            description={`Currently in your profile: ${currentCount}.${edited ? ' You edited this section, so it cannot be replaced.' : ''}`}
          >
            <SectionBody id={id} draft={draft} onDraftChange={onDraftChange} />
          </Card>
        )
      })}

      <Card title={`Found but not placed (${draft.unplaced?.length || 0})`} description="Text that fits none of the fields above. It stays in the raw text of the saved CV, so nothing is lost.">
        {draft.unplaced?.length ? (
          <div className="space-y-3">
            {draft.unplaced.map((item, i) => (
              <div key={`${item.label}-${i}`}>
                <p className="text-sm font-medium text-stone-800 dark:text-stone-200">{item.label}</p>
                <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-stone-50 p-3 text-xs text-stone-700 dark:bg-stone-950 dark:text-stone-300">{item.text}</pre>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-stone-500">Everything found was placed.</p>
        )}
      </Card>

      {draft.ignored?.length > 0 && (
        <Card title={`Ignored (${draft.ignored.length})`}>
          <ul className="list-inside list-disc text-sm text-stone-600 dark:text-stone-400">
            {draft.ignored.map((item) => <li key={item.name}>{item.name}: {item.reason}</li>)}
          </ul>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-stone-200 pt-4 dark:border-stone-800">
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Saved as "{(source.pdf && draft.fileName) || source.name}" in My CVs. {willBeActive(profile) ? 'You have no CV yet, so it becomes your active CV.' : 'It does not become your active CV.'}
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onDiscard} disabled={saving}>Discard</Button>
          <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save to my profile'}</Button>
        </div>
      </div>
    </div>
  )
}
