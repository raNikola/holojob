import { useEffect, useState } from 'react'
import { FileText, Loader2, Send, ShieldAlert, X } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { previewTailor } from '../../modules/jobs/pipelineRunner'

const NEVER_SENT = 'name, e-mail, phone, links, salary, questionnaire answers, notes, recruiter contacts'

/**
 * The only way CV text goes to an AI provider for tailoring. It shows exactly what would be sent (already redacted by the
 * server), to whom, and what the AI gate says, and sends nothing until the confirm button is pressed. The alternative
 * button makes rule-based documents, which send nothing.
 */
export default function TailorConfirmDialog({ opts, onClose, onConfirm, onRuleBased }) {
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    previewTailor(opts)
      .then((p) => { if (!cancelled) setPreview(p) })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
    // The preview is for the jobs as they are when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const jobs = preview?.jobs || []
  const blocked = (job) => job.refused || (job.gate && !job.gate.allowed) || !job.gate
  const reasons = [
    ...(preview && !preview.available ? [preview.availability || 'Claude Code is not available.'] : []),
    ...jobs.filter(blocked).map((j) => `${j.title || j.jobId}: ${j.refused || j.gate?.reason || 'refused'}`),
  ]
  const canSend = Boolean(preview) && preview.available && jobs.length > 0 && jobs.every((j) => !blocked(j))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="tailor-confirm-title">
      <button type="button" className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="Cancel" />
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col gap-4 overflow-y-auto rounded-xl border-2 border-amber-400 bg-white p-5 shadow-xl dark:border-amber-500 dark:bg-stone-950">
        <div className="flex items-start justify-between gap-3">
          <h3 id="tailor-confirm-title" className="flex items-center gap-2 font-display text-lg font-semibold text-stone-900 dark:text-stone-100">
            <ShieldAlert className="h-5 w-5 shrink-0 text-amber-600" />
            {!preview ? 'Preparing…' : `Send this text to ${preview.provider} to write ${jobs.length === 1 ? 'the documents' : `documents for ${jobs.length} jobs`}?`}
          </h3>
          <button type="button" onClick={onClose} className="rounded-lg p-1 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>

        {error && <Alert variant="error" title="Tailoring">{error}</Alert>}
        {!preview && !error && <Loader2 className="h-6 w-6 animate-spin text-teal-600" />}

        {preview && (
          <>
            <p className="text-sm text-stone-600 dark:text-stone-400">
              The text below goes to <strong>{preview.provider}</strong>, outside this server. Name, e-mail addresses, phone numbers and
              personal links are removed first. Any claim in the result that the profile does not state is rejected, and rule-based documents are made instead.
            </p>
            {reasons.length > 0 && (
              <Alert variant="error" title="This cannot be sent">
                <ul className="list-disc pl-4">{reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </Alert>
            )}
            {jobs.map((job, index) => (
              <details key={job.jobId} open={index === 0} className="rounded-lg border border-stone-200 p-3 dark:border-stone-700">
                <summary className="cursor-pointer text-sm font-semibold text-stone-800 dark:text-stone-200">
                  {job.title || job.jobId}{job.company ? ` at ${job.company}` : ''} ({job.characters.toLocaleString()} characters)
                </summary>
                {job.prompt && (
                  <pre data-testid="tailor-sent-text" className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200">{job.prompt}</pre>
                )}
              </details>
            ))}
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">Never sent</h4>
              <p className="mt-1 text-sm text-stone-700 dark:text-stone-300">{NEVER_SENT}</p>
            </div>
          </>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="secondary" onClick={onRuleBased} data-testid="tailor-rule-based"><FileText className="h-4 w-4" />Make rule-based documents (sends nothing)</Button>
          {preview && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={!canSend}
              data-testid="tailor-send"
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border-2 border-amber-500 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-amber-900/30 dark:text-amber-200"
            >
              <Send className="h-4 w-4" />Send to {preview.provider}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
