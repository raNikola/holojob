import { useEffect, useState } from 'react'
import { Loader2, Send, ShieldAlert, X } from 'lucide-react'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { previewJudge, runJudgedScoring } from '../../modules/jobs/pipelineRunner'

function recipient(preview) {
  if (!preview) return 'the configured LLM provider'
  return preview.model ? `${preview.provider} (${preview.model})` : preview.provider
}

function FieldList({ title, items, tone }) {
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wide ${tone}`}>{title}</h4>
      <p className="mt-1 text-sm text-stone-700 dark:text-stone-300">{items.join(', ')}</p>
    </div>
  )
}

function ConfirmDialog({ preview, sending, onCancel, onConfirm }) {
  const leaves = preview.leavesServer
  const nothingToJudge = preview.eligible === 0
  const confirmLabel = preview.toSend > 0
    ? `Send ${preview.toSend} ${preview.toSend === 1 ? 'job' : 'jobs'} to ${preview.provider}`
    : `Apply ${preview.cached} cached judgements (nothing sent)`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="judge-confirm-title">
      <button type="button" className="absolute inset-0 bg-black/50" onClick={onCancel} aria-label="Cancel" disabled={sending} />
      <div className="relative w-full max-w-xl space-y-4 rounded-xl border-2 border-amber-400 bg-white p-5 shadow-xl dark:border-amber-500 dark:bg-stone-950">
        <div className="flex items-start justify-between gap-3">
          <h3 id="judge-confirm-title" className="flex items-center gap-2 font-display text-lg font-semibold text-stone-900 dark:text-stone-100">
            <ShieldAlert className="h-5 w-5 shrink-0 text-amber-600" />
            {nothingToJudge
              ? 'No job scores high enough to judge'
              : `Send ${preview.eligible} job ${preview.eligible === 1 ? 'ad' : 'ads'} to ${recipient(preview)}?`}
          </h3>
          <button type="button" onClick={onCancel} disabled={sending} className="rounded-lg p-1 hover:bg-stone-100 dark:hover:bg-stone-800">
            <X className="h-5 w-5" />
          </button>
        </div>

        {nothingToJudge ? (
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Only jobs scoring {preview.threshold} or more locally are judged. None do, so nothing would be sent.
          </p>
        ) : (
          <>
            <p className="text-sm text-stone-600 dark:text-stone-400">
              {preview.cached} already judged (cached, not re-sent) · {preview.toSend} new {preview.toSend === 1 ? 'call' : 'calls'}.
              {' '}Each call sends one job ad and a digest of your profile
              {leaves ? <> to <strong>{preview.provider}</strong>, outside this server.</> : <> to <strong>{preview.provider}</strong>, a model on this machine.</>}
            </p>
            <FieldList title="Sent" items={preview.sent} tone="text-amber-700 dark:text-amber-400" />
            <FieldList title="Never sent" items={preview.neverSent} tone="text-emerald-700 dark:text-emerald-400" />
          </>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={sending}>Cancel</Button>
          {!nothingToJudge && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={sending}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border-2 border-amber-500 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-amber-900/30 dark:text-amber-200"
            >
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {confirmLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * The only UI entry to a judged scoring run. Kept apart from the local
 * pipeline actions, and it opens a confirmation listing exactly what is sent.
 */
export default function FitJudgementCard({ disabled, onBeforeRun, onScored }) {
  const [preview, setPreview] = useState(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [lastRun, setLastRun] = useState('')

  useEffect(() => {
    let cancelled = false
    previewJudge().then((p) => { if (!cancelled) setPreview(p) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const leaves = preview?.leavesServer !== false

  const openReview = async () => {
    setError('')
    setLoading(true)
    try {
      await onBeforeRun()
      setPreview(await previewJudge())
      setDialogOpen(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const confirm = async () => {
    setSending(true)
    setError('')
    try {
      const result = await runJudgedScoring()
      if (result.payload) onScored(result.payload)
      const line = (result.stdout || '').split('\n').find((l) => l.startsWith('judge:') && l.includes('judged'))
      setLastRun(`Last judged ${new Date().toLocaleString()}${line ? ` · ${line.replace('judge: ', '')}` : ''}`)
      setDialogOpen(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <section className={`rounded-xl border-2 p-4 ${leaves ? 'border-amber-300 bg-amber-50/40 dark:border-amber-600 dark:bg-amber-950/20' : 'border-stone-300 dark:border-stone-700'}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl space-y-1">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-stone-900 dark:text-stone-100">
            <ShieldAlert className={`h-4 w-4 ${leaves ? 'text-amber-600' : 'text-stone-500'}`} />
            {leaves ? 'Fit judgement — sends data off this server' : 'Fit judgement — runs on your local model'}
          </h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            Asks {recipient(preview)} to compare each ad with a digest of your profile. Local scoring runs
            first; only jobs scoring {preview?.threshold ?? 65}+ are sent. Re-scoring locally later keeps
            these judgements from the cache without sending anything.
          </p>
          {lastRun && <p className="text-xs text-stone-500">{lastRun}</p>}
        </div>
        <button
          type="button"
          onClick={openReview}
          disabled={disabled || loading || sending}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border-2 border-amber-500 bg-white px-4 py-2.5 text-sm font-semibold text-amber-900 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-stone-950 dark:text-amber-200"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
          Review and send…
        </button>
      </div>
      {error && <div className="mt-3"><Alert variant="error" title="Fit judgement">{error}</Alert></div>}
      {dialogOpen && preview && (
        <ConfirmDialog preview={preview} sending={sending} onCancel={() => setDialogOpen(false)} onConfirm={confirm} />
      )}
    </section>
  )
}
