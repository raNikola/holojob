import { useRef, useState } from 'react'
import { Loader2, Plus, Trash2, X } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import { validateManualJob } from '../../modules/jobs/manualJob'
import { addManualJob } from '../../modules/jobs/manualScoring'
import { jobHash } from '../../modules/jobs/jobRoute'
import { applySuggestions, fetchAdFields } from '../../modules/jobs/adFill'
import { normalizeJobUrl } from '../../modules/jobs/manualJob'

const LABELS = { title: 'Title', company: 'Company', location: 'Location', salary: 'Salary', description: 'Job description' }

/** Marks a value the page proposed; it goes away when the owner edits the field. */
const SuggestedTag = () => (
  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">suggested</span>
)

const EMPTY = {
  title: '', company: '', description: '', jobUrl: '', sourceUrl: '', location: '', salary: '', notes: '', extraLinks: [],
}

/**
 * Adds a job typed in by hand. "Fill from ad" asks the server to read the Job URL and proposes values for the fields that
 * are still empty (marked "suggested", editable, saved only by Save); Notes, extra links and the Source URL stay in this
 * browser's job record and are never part of any request.
 */
export default function AddJobDialog({ onClose, onSaved }) {
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [duplicate, setDuplicate] = useState(null)
  const [busy, setBusy] = useState(false)
  const [suggested, setSuggested] = useState({})
  const [adBusy, setAdBusy] = useState(false)
  const [adNote, setAdNote] = useState(null)
  const filledRef = useRef([])

  const edited = (field) => setSuggested((prev) => (prev[field] ? { ...prev, [field]: false } : prev))
  const set = (field) => (event) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }))
    edited(field)
  }
  const tag = (field) => (suggested[field] ? <SuggestedTag /> : null)

  const fillFromAd = async () => {
    if (adBusy) return
    setAdBusy(true)
    setAdNote(null)
    const result = await fetchAdFields(form.jobUrl)
    if (!result.ok) {
      setAdNote({ kind: 'error', text: result.message })
    } else {
      // Applied to the form as it is now: whatever was typed while the page loaded stays.
      setForm((prev) => {
        const next = applySuggestions(prev, result.fields)
        filledRef.current = next.filled
        return next.form
      })
      const filled = filledRef.current
      setSuggested((prev) => ({ ...prev, ...Object.fromEntries(filled.map((name) => [name, true])) }))
      setAdNote({
        kind: 'info',
        text: filled.length
          ? `Filled from the page: ${filled.map((name) => LABELS[name].toLowerCase()).join(', ')}. These are suggestions: edit them or leave them, nothing is saved until you click Save.`
          : 'The page had nothing new for the empty fields.',
      })
    }
    setAdBusy(false)
  }
  const setLink = (index, field, value) => setForm((prev) => ({
    ...prev, extraLinks: prev.extraLinks.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
  }))

  const save = async (openDetails) => {
    if (busy) return
    const found = validateManualJob(form)
    setErrors(found)
    setDuplicate(null)
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      const result = await addManualJob(form)
      if (result.status === 'duplicate') setDuplicate(result.existing)
      else onSaved(result.job, openDetails, result)
    } finally {
      setBusy(false)
    }
  }

  // Rows as the validator numbers them: blank rows are dropped, so error indexes follow the non-blank ones.
  const linkError = (row, index) => {
    const nonBlank = form.extraLinks.slice(0, index + 1).filter((r) => r.url.trim() || r.label.trim()).length - 1
    return row.url.trim() || row.label.trim() ? errors.extraLinks?.[nonBlank] : undefined
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-job-title"
      onKeyDown={(event) => { if (event.key === 'Escape') onClose() }}
    >
      <button type="button" className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="Close" tabIndex={-1} />
      <form
        noValidate
        onSubmit={(event) => { event.preventDefault(); save(false) }}
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col gap-4 overflow-y-auto rounded-xl border border-stone-200 bg-white p-5 shadow-xl dark:border-stone-700 dark:bg-stone-950"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="add-job-title" className="text-lg font-semibold text-stone-900 dark:text-stone-50">Add job</h2>
            <p className="text-xs text-stone-500">Scored on this server with the same local rules as every other job. Nothing is sent to an AI provider, and Notes, extra links and the Source URL never leave this browser.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        {duplicate && (
          <Alert variant="error">
            This link is already in your jobs: <a className="font-medium underline" href={jobHash(duplicate.jobId)} onClick={onClose}>{duplicate.title || 'open that job'}</a>. No second job was created.
          </Alert>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Input id="add-job-title-input" label="Title *" labelExtra={tag('title')} value={form.title} onChange={set('title')} error={errors.title} aria-required="true" aria-invalid={Boolean(errors.title)} autoFocus />
          <Input id="add-job-company" label="Company *" labelExtra={tag('company')} value={form.company} onChange={set('company')} error={errors.company} aria-required="true" aria-invalid={Boolean(errors.company)} />
        </div>
        <Textarea id="add-job-description" label="Job description" labelExtra={tag('description')} rows={8} value={form.description} onChange={set('description')} error={errors.description} aria-invalid={Boolean(errors.description)} placeholder="Paste the text of the ad. Without it the job is saved but not scored." />
        <p className="-mt-2 text-xs text-stone-500">Title and Company are required, and either a Job URL or the description.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Input id="add-job-url" label="Job URL" value={form.jobUrl} onChange={set('jobUrl')} error={errors.jobUrl} aria-invalid={Boolean(errors.jobUrl)} placeholder="https://" inputMode="url" />
            <Button type="button" variant="secondary" disabled={adBusy || !normalizeJobUrl(form.jobUrl)} onClick={fillFromAd}>
              {adBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {adBusy ? 'Reading the page…' : 'Fill from ad'}
            </Button>
            {adNote && <p role="status" className={`text-xs ${adNote.kind === 'error' ? 'text-red-600 dark:text-red-400' : 'text-stone-600 dark:text-stone-400'}`}>{adNote.text}</p>}
          </div>
          <Input id="add-job-source-url" label="Source URL" value={form.sourceUrl} onChange={set('sourceUrl')} error={errors.sourceUrl} aria-invalid={Boolean(errors.sourceUrl)} placeholder="Where you found it, e.g. a LinkedIn post (optional)" inputMode="url" />
          <Input id="add-job-location" label="Location" labelExtra={tag('location')} value={form.location} onChange={set('location')} placeholder="Left empty stays unknown" />
          <Input id="add-job-salary" label="Salary" labelExtra={tag('salary')} value={form.salary} onChange={set('salary')} placeholder="As in the ad, e.g. €2,500–3,000/month" />
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-stone-700 dark:text-stone-300">Extra links</legend>
          {form.extraLinks.map((row, index) => {
            const message = linkError(row, index)
            return (
              <div key={index} className="flex flex-wrap items-start gap-2">
                <Input className="min-w-[10rem] flex-1" id={`add-job-link-url-${index}`} label={`Link ${index + 1} URL`} value={row.url} onChange={(e) => setLink(index, 'url', e.target.value)} error={message} aria-invalid={Boolean(message)} placeholder="https://" inputMode="url" />
                <Input className="min-w-[8rem] flex-1" id={`add-job-link-label-${index}`} label={`Link ${index + 1} label`} value={row.label} onChange={(e) => setLink(index, 'label', e.target.value)} placeholder="e.g. Company page" />
                <Button type="button" variant="ghost" className="mt-7" aria-label={`Remove link ${index + 1}`} onClick={() => setForm((prev) => ({ ...prev, extraLinks: prev.extraLinks.filter((_, i) => i !== index) }))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            )
          })}
          <Button type="button" variant="secondary" onClick={() => setForm((prev) => ({ ...prev, extraLinks: [...prev.extraLinks, { url: '', label: '' }] }))}>
            <Plus className="h-4 w-4" /> Add link
          </Button>
        </fieldset>

        <Textarea id="add-job-notes" label="Notes (only for you, never sent to AI)" rows={3} value={form.notes} onChange={set('notes')} />

        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={() => save(true)}>Save and open details</Button>
          <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button>
        </div>
      </form>
    </div>
  )
}
