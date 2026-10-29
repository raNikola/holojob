import { useEffect, useRef, useState } from 'react'
import Input from '../ui/Input'
import Textarea from '../ui/Textarea'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { CHANNELS } from '../../modules/applications/applicationEnums'
import { foldApplication } from '../../modules/applications/foldApplication'
import { labelFor } from '../../modules/applications/stageRegistry'
import {
  EXTERNAL_CV,
  cvOptions,
  defaultCvOption,
  describeError,
  draftFrom,
  markApplied,
  newRequestId,
  panelMode,
  rebaseDraft,
  recordCv,
  restoreApplication,
  saveDraft,
  stageOptions,
  voidApplication,
  frozenFileUrl,
} from '../../modules/applications/trackerController'
import { useApplications } from '../../hooks/useApplications'
import { useProfile } from '../../context/ProfileContext'
import ApplicationTimeline from './ApplicationTimeline'

const SELECT_CLASS = 'w-full rounded-lg border border-stone-300 px-3 py-2.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50'
const LABEL_CLASS = 'mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300'
const titleCase = (value) => value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

const messageOf = describeError

/** Which CV was sent: tailored for the job, a library CV, a CV outside the app, or not recorded. */
function CvPicker({ id, options, value, label, onPick, onLabel }) {
  return (
    <div className="space-y-2">
      <label className={LABEL_CLASS} htmlFor={id}>CV used</label>
      <select id={id} className={SELECT_CLASS} value={value.key} onChange={(e) => onPick(options.find((o) => o.key === e.target.value))}>
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
      {value.key === EXTERNAL_CV.key && <Input label="Name of that CV" value={label} onChange={(e) => onLabel(e.target.value)} />}
    </div>
  )
}

function NewApplicationForm({ job, cache, onStatusChange }) {
  const { profile } = useProfile()
  const options = cvOptions(job, profile)
  const [cvLabel, setCvLabel] = useState('')
  const [form, setForm] = useState(() => ({
    cv: defaultCvOption(job, profile), requestId: newRequestId(), channel: 'company_site', appliedDate: new Date().toISOString().slice(0, 10), applicationUrl: '', separateAttempt: null,
  }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (next = form) => {
    setBusy(true)
    setError(null)
    try {
      await markApplied(job, cache, { ...next, cvLabel })
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
      <CvPicker id="tracker-cv" options={options} value={form.cv} label={cvLabel} onPick={(cv) => setForm({ ...form, cv })} onLabel={setCvLabel} />
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

/** The recorded CV as a link to its frozen copy, with "record" (none yet) or "correct" (needs a reason). */
function CvUsed({ app, folded }) {
  const { profile } = useProfile()
  const [open, setOpen] = useState(false)
  const [pick, setPick] = useState(null)
  const [label, setLabel] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const cv = folded.cv
  const recorded = cv && cv.kind !== 'unknown'
  const options = cvOptions({}, profile).filter((o) => o.key !== 'unknown')
  const earlier = (app.events ?? []).filter((e) => e.type === 'cv_recorded' && e.data.fileName && e.data.fileName !== cv?.fileName)
  const chosen = pick ?? options[0]

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await recordCv(app.id, chosen, { label, reason })
      setOpen(false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2 text-sm">
      <span className={LABEL_CLASS}>CV used</span>
      <p className="text-stone-700 dark:text-stone-300">
        {!recorded && 'Not recorded.'}
        {recorded && cv.fileName && <a className="text-teal-700 underline dark:text-teal-400" href={frozenFileUrl(app.id, cv.fileName)} download>{cv.label || cv.fileName}</a>}
        {recorded && !cv.fileName && (cv.label || 'A CV outside the app')}
      </p>
      {earlier.length > 0 && (
        <p className="text-xs text-stone-500">
          Earlier: {earlier.map((e) => <a key={e.id} className="mr-2 underline" href={frozenFileUrl(app.id, e.data.fileName)} download>{e.data.label || e.data.fileName}</a>)}
        </p>
      )}
      {!open && <Button variant="secondary" onClick={() => setOpen(true)}>{recorded ? 'Correct the CV' : 'Record the CV'}</Button>}
      {open && (
        <div className="space-y-2">
          <CvPicker id="tracker-cv-record" options={options} value={chosen} label={label} onPick={setPick} onLabel={setLabel} />
          {recorded && <Input label="Why is it being corrected?" value={reason} onChange={(e) => setReason(e.target.value)} />}
          {error && <Alert variant="error">{messageOf(error)}</Alert>}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={submit} disabled={busy}>Save CV</Button>
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function TrackedForm({ app, settings, onVoid }) {
  const folded = foldApplication(app)
  const [draft, setDraft] = useState(() => draftFrom(app))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  // The form stays mounted across events (it is keyed by application only), so an event written elsewhere on the
  // panel (a recorded CV, a stage move) must not wipe what is typed: untouched fields follow the server, edited ones stay.
  const base = useRef(draftFrom(app))
  useEffect(() => {
    const nextBase = draftFrom(app)
    setDraft((prev) => rebaseDraft(base.current, prev, nextBase))
    base.current = nextBase
  }, [app])
  const set = (field) => (e) => setDraft((prev) => ({ ...prev, [field]: e.target.value }))
  const stageLabel = (value) => (value.startsWith('outcome:') ? titleCase(value.slice(8)) : labelFor(value, settings))

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const made = await saveDraft(app.id, draft)
      if (made === 0) setNotice('Nothing to save: no field differs from the saved application.')
      else setDraft((prev) => ({ ...prev, newNote: '' }))
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
      <CvUsed app={app} folded={folded} />
      {folded.notes.length > 0 && (
        <ul className="space-y-1 text-sm text-stone-700 dark:text-stone-300">
          {folded.notes.map((n) => <li key={n.eventId}><span className="text-xs text-stone-500">{n.date}</span> {n.text}</li>)}
        </ul>
      )}
      <Textarea label="Add a note" value={draft.newNote} onChange={set('newNote')} rows={2} />
      {error && <Alert variant="error">{messageOf(error)}</Alert>}
      {notice && <Alert variant="info">{notice}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={save} disabled={busy}>Save application</Button>
        <Button variant="secondary" onClick={onVoid} disabled={busy}>Void (entered by mistake)</Button>
      </div>
      <ApplicationTimeline app={app} settings={settings} />
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
        {error && <Alert variant="error">{messageOf(error)}</Alert>}
        {voided ? (
          <Alert variant="info">
            This application was voided. It stays in the history and counts nowhere.
            <Button variant="secondary" className="mt-2" onClick={() => run(() => restoreApplication(shown.id, 'restored from Job Details'))}>Restore</Button>
          </Alert>
        ) : (
          <TrackedForm
            key={shown.id}
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
