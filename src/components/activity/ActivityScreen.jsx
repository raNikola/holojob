import { useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import Alert from '../ui/Alert'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Card from '../ui/Card'
import RunDetails from './RunDetails'
import { useRunHistory } from '../../modules/activity/useRunHistory.js'
import {
  NUMBER_HELP, PROOF_HELP, RETENTION_NOTE, STATUS_TONES, formatDuration, formatTime, savedShort, show, statusLabel, statusSentence, triggerLabel,
} from '../../modules/activity/runView.js'

const muted = 'text-stone-500 dark:text-stone-400'

function Figure({ label, value }) {
  return (
    <div className="min-w-[5.5rem]">
      <dt className={`text-xs ${muted}`}>{label}</dt>
      <dd className={value === 'Not recorded' ? `text-sm ${muted}` : 'text-sm font-semibold tabular-nums'}>{value}</dd>
    </div>
  )
}

function RunCard({ run, open, onToggle }) {
  const sentence = statusSentence(run)
  const id = `run-details-${run.runId}`
  return (
    <li className="rounded-lg border border-stone-200 p-3 dark:border-stone-800" data-testid="run-row">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{formatTime(run.startedAt)}</span>
        <Badge variant={STATUS_TONES[run.status] ?? 'low'}>{statusLabel(run.status)}</Badge>
        <span className={`text-sm ${muted}`}>{triggerLabel(run.trigger)}</span>
        <span className={`text-sm ${muted}`}>{run.status === 'running' ? 'In progress' : formatDuration(run.durationSeconds)}</span>
        <span className={`text-sm ${muted}`}>{run.issuesCount === 0 ? 'No issues' : `${run.issuesCount} ${run.issuesCount === 1 ? 'issue' : 'issues'}`}</span>
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        <Figure label="Returned" value={show(run.counts.returned)} />
        <Figure label="Collected" value={show(run.counts.collected)} />
        <Figure label="Saved (new)" value={savedShort(run)} />
        <Figure label="Filtered out" value={show(run.counts.filteredOut)} />
      </dl>
      {sentence && <p className="mt-2 text-sm text-stone-700 dark:text-stone-300">{sentence}</p>}
      <button
        type="button"
        className="mt-2 text-sm font-medium text-stone-700 underline underline-offset-2 dark:text-stone-300"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        {open ? 'Hide details' : 'Details'}
      </button>
      {open && <div id={id}><RunDetails run={run} /></div>}
    </li>
  )
}

/** The run history, read-only (S7b). It asks the server on open, on Refresh and on "Show more", and never on a timer. */
export default function ActivityScreen({ fetchFn }) {
  const history = useRunHistory({ fetchFn })
  const [open, setOpen] = useState(() => new Set())
  const toggle = (runId) => setOpen((was) => {
    const next = new Set(was)
    if (next.has(runId)) next.delete(runId)
    else next.add(runId)
    return next
  })
  const busy = history.status === 'loading'

  return (
    <div className="space-y-4">
      <Card
        title="Activity"
        description="What each run read, kept and saved, and why a source did or did not count as proven."
        action={
          <Button variant="secondary" onClick={history.refresh} disabled={busy}>
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Refresh
          </Button>
        }
      >
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">What the numbers mean</summary>
          <dl className="mt-2 space-y-1">
            {NUMBER_HELP.map(([label, help]) => (
              <div key={label}><dt className="inline font-medium">{label}: </dt><dd className="inline">{help}</dd></div>
            ))}
          </dl>
          <p className={`mt-2 ${muted}`}>{PROOF_HELP}</p>
        </details>
      </Card>

      {history.status === 'error' && (
        <Alert variant="error" title="The run history could not be loaded">
          <p>{history.error}</p>
          <Button className="mt-3" variant="secondary" onClick={history.refresh}>Try again</Button>
        </Alert>
      )}

      {(history.status === 'idle' || (busy && history.runs.length === 0)) && (
        <p role="status" className={`flex items-center gap-2 text-sm ${muted}`}><Loader2 className="h-4 w-4 animate-spin" />Loading the run history…</p>
      )}

      {history.status === 'ready' && history.runs.length === 0 && (
        <Card><p role="status">No runs yet. A run appears here once a Re-scrape or a pipeline run has started.</p></Card>
      )}

      {history.runs.length > 0 && (
        <Card>
          <ul className="space-y-3" aria-label="Runs, newest first">
            {history.runs.map((run) => <RunCard key={run.runId} run={run} open={open.has(run.runId)} onToggle={() => toggle(run.runId)} />)}
          </ul>
          {history.next && (
            <div className="mt-4">
              <Button variant="secondary" onClick={history.loadMore} disabled={history.more === 'loading'}>
                {history.more === 'loading' ? 'Loading…' : 'Show more'}
              </Button>
              {history.more === 'error' && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{history.moreError} Press Show more to try again.</p>}
            </div>
          )}
          <p className={`mt-4 text-xs ${muted}`}>{RETENTION_NOTE}</p>
        </Card>
      )}
    </div>
  )
}
