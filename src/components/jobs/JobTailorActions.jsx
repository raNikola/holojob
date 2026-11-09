import { useState } from 'react'
import { Download, FileText, Loader2, Sparkles } from 'lucide-react'
import Button from '../ui/Button'
import OperationConsole from '../ui/OperationConsole'
import { useOperationLog } from '../../hooks/useOperationLog'
import {
  buildTailorCommand,
  getTailoredFilenames,
  resumeDownloadUrl,
  runTailor,
} from '../../modules/jobs/pipelineRunner'
import { tailoringBlocked } from '../../modules/jobs/keptRescore'
import { useProfile } from '../../context/ProfileContext'
import { runAiFeature } from '../../modules/ai/aiClient'
import TailorConfirmDialog from './TailorConfirmDialog'
import { CHECKS_FAILED, CHECKS_PASSED, CHECK_LIMITS } from '../../modules/jobs/factCheckNote'

export const NOT_IN_SCORED_LIST = 'Documents are made from the latest scored list, and this ad is not in it (it was kept, or it is no longer listed). Documents cannot be generated for it until a search lists it again.'

export default function JobTailorActions({ job, apiAvailable, onJobUpdated, compact = false }) {
  const { profile } = useProfile()
  const [running, setRunning] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [enhancement, setEnhancement] = useState(job.aiInsights?.resumeEnhancement || null)
  const log = useOperationLog()
  const aiLog = useOperationLog()
  const assets = job.tailoredAssets

  // The button only opens the confirm dialog; nothing is sent until the dialog's own button is pressed.
  const handleGenerate = () => {
    setError(null)
    // Tailoring reads the latest scored list on the server. A kept ad, or one no longer listed, is not in it, whatever text the browser holds.
    if (tailoringBlocked(job)) {
      setError(NOT_IN_SCORED_LIST)
      log.append(`Not started: ${NOT_IN_SCORED_LIST}`)
      return
    }
    setConfirming(true)
  }

  const generate = async (mode) => {
    setConfirming(false)
    setRunning(true)
    log.start('Starting: generating the resume and the cover letter…')
    try {
      const result = await runTailor(
        { jobId: job.jobId, profile, ...mode },
        { onLog: log.append },
      )
      const updated = result.payload?.jobs?.find((j) => j.jobId === job.jobId)
      if (updated) {
        // The tailor run adds only `tailoredAssets`; the rest of its copy (status, outreach) may be older than this one.
        onJobUpdated?.({ ...job, tailoredAssets: updated.tailoredAssets })
        log.append('Saved to job record.')
      } else {
        throw new Error('This job was not found in the generated documents.')
      }
    } catch (e) {
      setError(e.message)
      log.append(`Error: ${e.message}`)
    } finally {
      setRunning(false)
      log.stop()
    }
  }

  const handleEvaluate = async () => {
    setError(null)
    setEvaluating(true)
    aiLog.start('Starting AI resume evaluation…')
    try {
      const result = await runAiFeature('resumeEnhancement', { job, onLog: aiLog.append })
      setEnhancement(result.data)
      onJobUpdated?.({
        ...job,
        aiInsights: {
          ...(job.aiInsights || {}),
          resumeEnhancement: result.data,
          generatedAt: result.meta?.generatedAt,
        },
      })
      aiLog.append('Evaluation complete.')
    } catch (e) {
      setError(e.message)
      aiLog.append(`Error: ${e.message}`)
    } finally {
      setEvaluating(false)
      aiLog.stop()
    }
  }

  const files = getTailoredFilenames(assets)
  const busy = running || evaluating

  if (!apiAvailable) {
    if (compact) return null
    if (tailoringBlocked(job)) return <p className="text-xs text-stone-500">{NOT_IN_SCORED_LIST}</p>
    return (
      <p className="text-xs text-stone-500">
        Run: <code className="text-[length:calc(var(--text-xs)-0.125rem)]">{buildTailorCommand({ jobId: job.jobId })}</code>
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {confirming && (
        <TailorConfirmDialog
          opts={{ jobId: job.jobId, profile }}
          onClose={() => setConfirming(false)}
          onConfirm={() => generate({ confirm: true })}
          onRuleBased={() => generate({ noLlm: true })}
        />
      )}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      {!assets?.resumeMd ? (
        <Button
          variant="secondary"
          className="!px-2 !py-1 !text-xs"
          onClick={handleGenerate}
          disabled={busy}
        >
          {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
          {running ? 'Generating…' : 'Generate resume'}
        </Button>
      ) : (
        <>
          <div className="flex flex-wrap gap-1">
            {files.map((f) => (
              <a
                key={f.key}
                href={resumeDownloadUrl(job.jobId, f.filename)}
                download={f.filename}
                className="inline-flex items-center gap-1 rounded-md border border-stone-200 px-2 py-1 text-xs font-medium text-teal-700 hover:bg-stone-50 dark:border-stone-700 dark:text-teal-400 dark:hover:bg-stone-800"
              >
                {f.filename.endsWith('.pdf') ? <Download className="h-3 w-3" /> : <FileText className="h-3 w-3" />}
                {f.label}
              </a>
            ))}
            <button
              type="button"
              onClick={handleGenerate}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"
            >
              {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
              Generate again
            </button>
          </div>
          <Button
            variant="secondary"
            className="!px-2 !py-1 !text-xs self-start"
            onClick={handleEvaluate}
            disabled={busy}
          >
            {evaluating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
            {evaluating ? 'Evaluating…' : 'Evaluate with AI'}
          </Button>
          {enhancement && (
            <details className="rounded-lg border border-stone-200 p-2 text-xs dark:border-stone-700">
              <summary className="cursor-pointer font-medium text-stone-600 dark:text-stone-400">AI suggestions (verify facts)</summary>
              <div className="mt-2 space-y-2 text-stone-700 dark:text-stone-300">
                {enhancement.atsScoreEstimate && <p>ATS estimate: {enhancement.atsScoreEstimate}</p>}
                {enhancement.missingKeywords?.length > 0 && (
                  <p>Missing keywords: {enhancement.missingKeywords.join(', ')}</p>
                )}
                {enhancement.bulletSuggestions?.map((b) => <p key={b}>• {b}</p>)}
              </div>
            </details>
          )}
        </>
      )}
      <OperationConsole
        lines={log.lines}
        active={log.active}
        title={running ? 'Generating documents…' : 'Generation log'}
      />
      <OperationConsole
        lines={aiLog.lines}
        active={aiLog.active}
        title={evaluating ? 'AI evaluation…' : 'AI log'}
      />
      {assets?.provenancePassed === false && (
        <div role="status" data-testid="tailor-provenance-issues" className="text-[13px] leading-5 text-amber-900 dark:text-amber-200">
          <p>{CHECKS_FAILED}. These documents cannot be attached to an application until they are generated again:</p>
          <ul className="list-disc pl-4">
            {(assets.provenanceIssues || []).slice(0, 5).map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      )}
      {assets?.provenancePassed === true && (
        <details open data-testid="tailor-checks-passed" className="rounded-lg border border-stone-200 bg-stone-50 p-2 text-[13px] leading-5 text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200">
          <summary className="cursor-pointer font-medium">{CHECKS_PASSED}. Read it before you send it.</summary>
          <p className="mt-1">{CHECK_LIMITS}</p>
        </details>
      )}
      {(assets?.llmIssues || []).length > 0 && (
        <div role="status" data-testid="tailor-llm-issues" className="text-[13px] leading-5 text-stone-800 dark:text-stone-200">
          <p>Why the AI draft was not used:</p>
          <ul className="list-disc pl-4">
            {assets.llmIssues.slice(0, 5).map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
