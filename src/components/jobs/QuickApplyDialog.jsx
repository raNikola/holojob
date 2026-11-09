import { useState } from 'react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Input from '../ui/Input'
import SelectField from '../ui/SelectField'
import { useProfile } from '../../context/ProfileContext'
import { CHANNELS } from '../../modules/applications/applicationEnums'
import { CHANNEL_LABELS } from '../../modules/applications/applicationStatistics'
import { cvOptions, describeError } from '../../modules/applications/trackerController'
import { quickApplyForm, submitQuickApply } from '../../modules/applications/quickApply'

/**
 * Opens from the Applied button on the Jobs table. Nothing is written until "Save application" and the server's answer; Cancel,
 * Escape and a failed save leave the job as it was. Full editing (contacts, notes, stage) stays on Job Details.
 */
export default function QuickApplyDialog({ job, cache, onClose, onSaved }) {
  const { profile } = useProfile()
  const [form, setForm] = useState(() => quickApplyForm(job, profile))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const options = cvOptions(job, profile)
  const set = (patch) => setForm((prev) => ({ ...prev, ...patch }))

  const save = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await submitQuickApply(job, cache, form, { onSaved })
      onClose()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="quick-apply-title"
      onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}
    >
      <button type="button" className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="Close" tabIndex={-1} />
      <form
        noValidate
        onSubmit={(event) => { event.preventDefault(); save() }}
        className="relative w-full max-w-md space-y-4 rounded-xl bg-white p-5 shadow-xl dark:bg-stone-900"
      >
        <div>
          <h2 id="quick-apply-title" className="text-base font-semibold text-stone-900 dark:text-stone-50">Record application</h2>
          <p className="text-sm text-stone-600 dark:text-stone-400">{job.title}{job.company ? `, ${job.company}` : ''}</p>
          <p className="mt-1 text-xs text-stone-500">Saved in the tracker on the server. The job shows Applied only after it is saved.</p>
        </div>
        {error && (
          <Alert variant="error">
            {describeError(error)}
            {error.extra?.conflictingId && ' Open full details to see it, or to record a separate attempt through another channel.'}
          </Alert>
        )}
        <Input label="Applied on" id="quick-apply-date" type="date" value={form.appliedDate} onChange={(e) => set({ appliedDate: e.target.value })} />
        <SelectField
          label="Channel" id="quick-apply-channel" value={form.channel} onChange={(value) => set({ channel: value })}
          options={CHANNELS.map((value) => ({ value, label: CHANNEL_LABELS[value] ?? value }))}
        />
        <SelectField
          label="CV sent" id="quick-apply-cv" value={form.cv.key} placeholder="Not recorded yet"
          onChange={(key) => set({ cv: options.find((o) => o.key === key) ?? form.cv })}
          options={options.map((o) => ({ value: o.key, label: o.label }))}
        />
        <Input label="Application URL (optional)" id="quick-apply-url" value={form.applicationUrl} onChange={(e) => set({ applicationUrl: e.target.value })} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save application'}</Button>
        </div>
      </form>
    </div>
  )
}
