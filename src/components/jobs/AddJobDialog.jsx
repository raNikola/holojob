import { useState } from 'react'
import { Loader2, Plus, Trash2, X } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import { validateManualJob } from '../../modules/jobs/manualJob'
import { addManualJob } from '../../modules/jobs/manualScoring'
import { jobHash } from '../../modules/jobs/jobRoute'
import { LABELS, applyFill, clearSuggested, fetchAdFields, previewAdAi, runAdAi, stillMissing } from '../../modules/jobs/adFill'
import { normalizeJobUrl } from '../../modules/jobs/manualJob'

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
  // The form, the "suggested" marks and the note change together, in one transition (applyFill), so they cannot disagree.
  const [draft, setDraft] = useState({ form: EMPTY, suggested: {}, note: null })
  const { form, suggested, note: adNote } = draft
  const setForm = (update) => setDraft((prev) => ({ ...prev, form: typeof update === 'function' ? update(prev.form) : update }))
  const setNote = (note) => setDraft((prev) => ({ ...prev, note }))
  const [errors, setErrors] = useState({})
  const [duplicate, setDuplicate] = useState(null)
  const [busy, setBusy] = useState(false)
  const [adBusy, setAdBusy] = useState(false)
  const [adPage, setAdPage] = useState(null) // { token, missing } of the page last read
  const [aiPanel, setAiPanel] = useState(null) // { loading } | { preview } | { error } | { preview, sending }

  const set = (field) => (event) => {
    const { value } = event.target
    setDraft((prev) => clearSuggested({ ...prev, form: { ...prev.form, [field]: value } }, field))
    // A different address is a different page: what was read from the old one is no longer offered to the AI step.
    if (field === 'jobUrl') {
      setAdPage(null)
      setAiPanel(null)
    }
  }
  const tag = (field) => (suggested[field] ? <SuggestedTag /> : null)

  const fillFromAd = async () => {
    if (adBusy) return
    setAdBusy(true)
    setNote(null)
    setAiPanel(null)
    const result = await fetchAdFields(form.jobUrl)
    if (!result.ok) {
      setAdPage(null)
      setNote({ kind: 'error', text: result.message })
    } else {
      setAdPage({ token: result.token, missing: result.missing })
      // Applied to the form as it is when the answer arrives: whatever was typed while the page loaded stays.
      setDraft((prev) => applyFill(prev, result.fields, { source: 'page' }))
    }
    setAdBusy(false)
  }

  // Fields the page did not state that are still empty: what the AI step could be asked for.
  const askable = adPage ? stillMissing(form, adPage.missing) : []

  const openAiPanel = async () => {
    setAiPanel({ loading: true })
    const preview = await previewAdAi({ token: adPage.token, want: askable })
    setAiPanel(preview.ok ? { preview } : { error: preview.message })
  }

  const sendToAi = async () => {
    const { preview } = aiPanel
    setAiPanel({ preview, sending: true })
    const result = await runAdAi({ token: adPage.token, want: preview.want })
    if (!result.ok) {
      setAiPanel({ preview, error: result.message })
      return
    }
    setDraft((prev) => applyFill(prev, result.fields, { source: 'ai', wanted: preview.want }))
    setAiPanel(null)
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
            {askable.length > 0 && !aiPanel && (
              <Button type="button" variant="secondary" onClick={openAiPanel}>Extract the missing fields with AI</Button>
            )}
            {adNote && <p role="status" className={`text-xs ${adNote.kind === 'error' ? 'text-red-600 dark:text-red-400' : 'text-stone-600 dark:text-stone-400'}`}>{adNote.text}</p>}
          </div>
          <Input id="add-job-source-url" label="Source URL" value={form.sourceUrl} onChange={set('sourceUrl')} error={errors.sourceUrl} aria-invalid={Boolean(errors.sourceUrl)} placeholder="Where you found it, e.g. a LinkedIn post (optional)" inputMode="url" />
          <Input id="add-job-location" label="Location" labelExtra={tag('location')} value={form.location} onChange={set('location')} placeholder="Left empty stays unknown" />
          <Input id="add-job-salary" label="Salary" labelExtra={tag('salary')} value={form.salary} onChange={set('salary')} placeholder="As in the ad, e.g. €2,500–3,000/month" />
        </div>

        {aiPanel && (
          <div className="space-y-3 rounded-lg border-2 border-amber-400 p-3 text-sm dark:border-amber-500" role="group" aria-label="Extract the missing fields with AI">
            {aiPanel.loading && <p>Checking what would be sent…</p>}
            {aiPanel.error && <Alert variant="error">{aiPanel.error}</Alert>}
            {aiPanel.preview && (
              <>
                <p>
                  This sends the text below to <strong>Claude Code (Anthropic)</strong> and asks only for: <strong>{aiPanel.preview.want.map((name) => LABELS[name].toLowerCase()).join(', ')}</strong>.
                  The page text is the ad as fetched, with names, e-mail addresses, phone numbers and links removed
                  ({aiPanel.preview.removed.emails} e-mails, {aiPanel.preview.removed.phones} phones, {aiPanel.preview.removed.links} links, {aiPanel.preview.removed.names} names).
                  Nothing else is sent: not your Notes, extra links, Source URL, profile or CV. The AI may only copy what the text says; anything it cannot find stays empty.
                </p>
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-stone-50 p-2 text-xs dark:bg-stone-900" aria-label="Text that would be sent">{aiPanel.preview.text}</pre>
                {aiPanel.preview.gate.allowed
                  ? <p className="text-xs text-stone-600 dark:text-stone-400">Covered by your Claude subscription (no charge, counted in its daily limit).</p>
                  : <Alert variant="error">Not sent: {aiPanel.preview.gate.reason}. You can still fill the fields in by hand.</Alert>}
              </>
            )}
            <div className="flex flex-wrap gap-2">
              {aiPanel.preview && (
                <Button type="button" disabled={!aiPanel.preview.gate.allowed || aiPanel.sending} onClick={sendToAi}>
                  {aiPanel.sending ? 'Reading…' : 'Send to Claude Code'}
                </Button>
              )}
              <Button type="button" variant="ghost" disabled={aiPanel.sending} onClick={() => setAiPanel(null)}>{aiPanel.preview ? 'Cancel, fill in by hand' : 'Close'}</Button>
            </div>
          </div>
        )}

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
