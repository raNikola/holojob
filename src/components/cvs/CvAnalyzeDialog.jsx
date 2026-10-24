import { useEffect, useState } from 'react'
import { Loader2, Send, ShieldAlert, X } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { cvAnalysisInput, previewCvAnalysis, runCvAnalysis } from '../../modules/cvs/cvAnalyzeApi'

function Removed({ removed }) {
  const parts = [
    [removed.names, 'name'], [removed.emails, 'e-mail'], [removed.phones, 'phone number'], [removed.links, 'link'],
  ].filter(([n]) => n > 0).map(([n, label]) => `${n} ${label}${n === 1 ? '' : 's'}`)
  return <>{parts.length ? parts.join(', ') : 'nothing needed removing'}</>
}

/**
 * The only way a CV's text goes to an LLM provider. It shows what would be sent,
 * to whom, and sends nothing until the confirm button is pressed.
 */
export default function CvAnalyzeDialog({ profile, cv, force = false, onClose, onDone }) {
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const input = cvAnalysisInput(profile, cv)

  useEffect(() => {
    let cancelled = false
    previewCvAnalysis(cvAnalysisInput(profile, cv))
      .then((p) => { if (!cancelled) setPreview(p) })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
    // The preview is for the CV as it is when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const useCache = preview?.cached && !force
  const confirm = async () => {
    setSending(true)
    setError('')
    try {
      onDone(await runCvAnalysis(input, { force }))
    } catch (e) {
      setError(e.message)
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="cv-analyze-title">
      <button type="button" className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="Cancel" disabled={sending} />
      <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col gap-4 overflow-y-auto rounded-xl border-2 border-amber-400 bg-white p-5 shadow-xl dark:border-amber-500 dark:bg-stone-950">
        <div className="flex items-start justify-between gap-3">
          <h3 id="cv-analyze-title" className="flex items-center gap-2 font-display text-lg font-semibold text-stone-900 dark:text-stone-100">
            <ShieldAlert className="h-5 w-5 shrink-0 text-amber-600" />
            {!preview ? 'Preparing…' : useCache ? 'Show the saved analysis? Nothing is sent'
              : `Send this CV text to ${preview.provider}${preview.model ? ` (${preview.model})` : ''}?`}
          </h3>
          <button type="button" onClick={onClose} disabled={sending} className="rounded-lg p-1 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>

        {error && <Alert variant="error" title="CV analysis">{error}</Alert>}
        {!preview && !error && <Loader2 className="h-6 w-6 animate-spin text-teal-600" />}

        {preview && (
          <>
            <p className="text-sm text-stone-600 dark:text-stone-400">
              {useCache
                ? 'This CV was analyzed before with the same text, provider and model, so the saved result is used.'
                : preview.leavesServer
                  ? <>The text below goes to <strong>{preview.provider}</strong>, outside this server.</>
                  : <>The text below goes to <strong>{preview.provider}</strong>, a model on this machine.</>}
              {' '}Removed before sending: <Removed removed={preview.removed} />.
            </p>
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                Exactly what is sent ({preview.characters.toLocaleString()} characters)
              </h4>
              <pre data-testid="cv-sent-text" className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200">{preview.sentText}</pre>
            </div>
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">Never sent</h4>
              <p className="mt-1 text-sm text-stone-700 dark:text-stone-300">{preview.neverSent.join(', ')}</p>
            </div>
          </>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={sending}>Cancel</Button>
          {preview && (
            <button
              type="button"
              onClick={confirm}
              disabled={sending}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border-2 border-amber-500 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-amber-900/30 dark:text-amber-200"
            >
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {useCache ? 'Show saved analysis' : `Send to ${preview.provider}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
