import { useState } from 'react'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { CHANNELS } from '../../modules/applications/applicationEnums'
import { foldApplication } from '../../modules/applications/foldApplication'
import { labelFor } from '../../modules/applications/stageRegistry'
import {
  draftFrom,
  markApplied,
  newRequestId,
  panelMode,
  restoreApplication,
  saveDraft,
  stageOptions,
  voidApplication,
} from '../../modules/applications/trackerController'
import { useApplications } from '../../hooks/useApplications'

const SELECT_CLASS = 'w-full rounded-lg border border-stone-300 px-3 py-2.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50'
const LABEL_CLASS = 'mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300'
const titleCase = (value) => value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

function messageOf(error) {
  if (error.extra?.code === 'tracking_disabled') return 'Application tracking is switched off in the tracker settings.'
  return error.message
}

function NewApplicationForm({ job, cache, onStatusChange }) {
  const [form, setForm] = useState(() => ({
    requestId: newRequestId(), channel: 'company_site', appliedDate: new Date().toISOString().slice(0, 10), applicationUrl: '', separateAttempt: null,
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (next = form) => {
    setBusy(true)
    setError(null)
    try {
      await markApplied(job, cache, next)
      onStatusChange?.(job.jobId, 'applied_manually')
      setForm({ ...next, requestId: newRequestId(), separateAttempt: null })
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={LABEL_CLASS} htmlFor="tracker-channel">Channel</label>
          <select id="tracker-channel" className={SELECT_CLASS} value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
            {CHANNELS.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
          </select>
        </div>
        <Input label="Applied date" type="date" value={form.appliedDate} onChange={(e) => setForm({ ...form, appliedDate: e.target.value })} />
        <Input label="Application URL" value={form.applicationUrl} onChange={(e) => setForm({ ...form, applicationUrl: e.target.value })} />
      </div>
      {error && (
        <Alert variant="error">
          {messageOf(error)}
          {error.extra?.conflictingId && !form.separateAttempt && (
            <Button variant="secondary" className="mt-2" onClick={() => submit({ ...form, separateAttempt: 'different_channel' })} disabled={busy}>
              This is a separate attempt through another channel
            </Button>
          )}
        </Alert>
      )}
      <Button variant="secondary" onClick={() => submit()} disabled={busy}>Mark as applied</Button>
    </div>
  )
}

function TrackedForm({ app, settings, onVoid }) {
  const folded = foldApplication(app)
  const [draft, setDraft] = useState(() => draftFrom(app))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const set = (field) => (e) => setDraft((prev) => ({ ...prev, [field]: e.target.value }))
  const stageLabel = (value) => (value.startsWith('outcome:') ? titleCase(value.slice(8)) : labelFor(value, settings))

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await saveDraft(app.id, draft)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={LABEL_CLASS} htmlFor="tracker-stage">Stage</label>
          <select id="tracker-stage" className={SELECT_CLASS} value={draft.stage} onChange={set('stage')}>
            {stageOptions(settings, folded).map((o) => <option key={o.value} value={o.value}>{stageLabel(o.value)}</option>)}
          </select>
        </div>
        <Input label="Applied date" type="date" value={draft.appliedDate} onChange={set('appliedDate')} />
        <Input label="Follow-up date" type="date" value={draft.followUpDate} onChange={set('followUpDate')} />
        <div>
          <span className={LABEL_CLASS}>Channel</span>
          <p className="py-2 text-sm text-stone-600 dark:text-stone-400">
            {titleCase(app.attempt.channel)}{app.attempt.applicationUrl ? ` · ${app.attempt.applicationUrl}` : ''}
          </p>
        </div>
        <Input label="Recruiter name" value={draft.recruiterName} onChange={set('recruiterName')} />
        <Input label="Recruiter email" value={draft.recruiterEmail} onChange={set('recruiterEmail')} />
        <Input label="Recruiter LinkedIn" value={draft.recruiterLinkedIn} onChange={set('recruiterLinkedIn')} />
      </div>
      {folded.notes.length > 0 && (
        <ul className="space-y-1 text-sm text-stone-700 dark:text-stone-300">
          {folded.notes.map((n) => <li key={n.eventId}><span className="text-xs text-stone-500">{n.date}</span> {n.text}</li>)}
        </ul>
      )}
      <Textarea label="Add a note" value={draft.newNote} onChange={set('newNote')} rows={2} />
      {error && <Alert variant="error">{error.extra?.code === 'tracking_disabled' ? messageOf(error) : error.message}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={save} disabled={busy}>Save application</Button>
        <Button variant="secondary" onClick={onVoid} disabled={busy}>Void (entered by mistake)</Button>
      </div>
    </div>
  )
}

export default function ApplicationTrackerPanel({ job, onStatusChange }) {
  const cache = useApplications()
  const mode = panelMode(job, cache)
  const [pickedId, setPickedId] = useState(null)
  const [error, setError] = useState(null)

  const run = async (action) => {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(e)
    }
  }

  let body
  if (mode.mode === 'loading') {
    body = <p className="text-sm text-stone-600 dark:text-stone-400">Loading the application tracker…</p>
  } else if (mode.mode === 'error') {
    body = <Alert variant="error">The application tracker could not be loaded: {mode.message}</Alert>
  } else if (mode.mode === 'migrate-first') {
    body = (
      <Alert variant="info">
        Run the migration first (Settings → Application tracking migration). This job still has tracking saved in the
        old format{mode.reason ? `, and it cannot be migrated: ${mode.reason}` : ''}, so a new entry is not allowed until it is moved into the tracker.
      </Alert>
    )
  } else if (mode.mode === 'new') {
    body = <NewApplicationForm job={job} cache={cache} onStatusChange={onStatusChange} />
  } else {
    const shown = mode.attempts.find((a) => a.id === pickedId) ?? mode.current
    const voided = foldApplication(shown).voided
    const closed = Boolean(foldApplication(shown).outcome)
    body = (
      <div className="space-y-3">
        {mode.attempts.length > 1 && (
          <div>
            <label className={LABEL_CLASS} htmlFor="tracker-attempt">Attempt</label>
            <select id="tracker-attempt" className={SELECT_CLASS} value={shown.id} onChange={(e) => setPickedId(e.target.value)}>
              {mode.attempts.map((a, i) => (
                <option key={a.id} value={a.id}>
                  {`Attempt ${i + 1} · ${a.attempt.appliedDate ?? 'no date'} · ${titleCase(a.attempt.channel)}${foldApplication(a).voided ? ' · voided' : ''}`}
                </option>
              ))}
            </select>
          </div>
        )}
        {error && <Alert variant="error">{error.message}</Alert>}
        {voided ? (
          <Alert variant="info">
            This application was voided. It stays in the history and counts nowhere.
            <Button variant="secondary" className="mt-2" onClick={() => run(() => restoreApplication(shown.id, 'restored from Job Details'))}>Restore</Button>
          </Alert>
        ) : (
          <TrackedForm
            key={`${shown.id}:${shown.events.length}`}
            app={shown}
            settings={cache.settings}
            onVoid={() => window.confirm('Void this application? It stays in the history but is removed from every list.')
              && run(() => voidApplication(shown.id, 'voided from Job Details'))}
          />
        )}
        {!voided && closed && (
          <details className="text-sm">
            <summary className="cursor-pointer text-stone-600 dark:text-stone-400">Apply to this job again</summary>
            <div className="mt-2"><NewApplicationForm job={job} cache={cache} onStatusChange={onStatusChange} /></div>
          </details>
        )}
        {voided && mode.attempts.every((a) => foldApplication(a).voided) && (
          <details className="text-sm">
            <summary className="cursor-pointer text-stone-600 dark:text-stone-400">Record a new application</summary>
            <div className="mt-2"><NewApplicationForm job={job} cache={cache} onStatusChange={onStatusChange} /></div>
          </details>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3 border-t border-stone-200 pt-4 dark:border-stone-800">
      <h3 className="text-sm font-semibold text-stone-800 dark:text-stone-200">Application tracking</h3>
      {body}
    </div>
  )
}
