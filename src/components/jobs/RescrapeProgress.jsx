import { useState } from 'react'
import CancelRun from '../activity/CancelRun'
import { cancelledText, eventText, latestEventText } from '../../modules/jobs/rescrapeRun.js'

function eventTime(event) {
  const date = new Date(event.at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString()
}

/** Cancel for a Re-scrape that is going. Cancel is the same control Activity uses; this screen's own poll is unchanged. */
function RunActions({ view }) {
  const [said, setSaid] = useState(null)
  const cancellable = view.active && view.run.orchestrator === 'rescrape'
  if (!cancellable && !said) return null
  return (
    <div className="flex flex-wrap items-center gap-3">
      {cancellable && (
        <CancelRun runId={view.run.runId} requested={Boolean(view.cancelRequested)} onAnswer={(answer) => setSaid(answer.kind === 'requested' ? null : answer)} />
      )}
      {said && <p role="status" className={said.kind === 'refused' ? 'text-red-700 dark:text-red-300' : ''}>{said.message}</p>}
    </div>
  )
}

/** What a Re-scrape that is going, or one that ended badly, needs said next to the buttons: Cancel, and what a dead run or an unfinished save left behind. The event log lives in the Activity tab. */
export default function RescrapeProgress({ view }) {
  if (!view.run) return null
  const { incompleteCommit: commit } = view
  return (
    <div role="status" className="w-full space-y-1 text-xs text-stone-600 dark:text-stone-400">
      <RunActions view={view} />
      {view.run.status === 'interrupted' && (
        <p className="text-amber-700 dark:text-amber-400">The last run was interrupted before it finished. It is not resumed: start it again when you want fresh jobs.</p>
      )}
      {view.run.status === 'cancelled' && <p className="text-amber-700 dark:text-amber-400">{cancelledText(view.run.cancel)}</p>}
      {view.run.cancel?.outcome === 'imported_before_cancel' && (
        <p className="text-amber-700 dark:text-amber-400">The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped.</p>
      )}
      {view.active && view.cancelRequested && <p>Cancel requested. The run stops at its next safe point.</p>}
      {commit && (
        <p className="text-amber-700 dark:text-amber-400">
          {commit.unreadable
            ? 'A save of the job files is incomplete, and its record cannot be read.'
            : `A save of the job files is incomplete. Written: ${commit.written.join(', ') || 'none'}. Not written: ${commit.pending.join(', ') || 'none'}.`}
          {' '}These files may not match each other. Nothing was repaired; a finished Re-scrape writes them all again.
        </p>
      )}
      {view.scoringBehind && <p className="text-amber-700 dark:text-amber-400">The latest jobs have not been scored yet. Re-score to score them.</p>}
    </div>
  )
}

/** The latest Re-scrape's events (the server keeps the events of the latest run for this view), shown in the Activity tab. */
export function RescrapeEventLog({ view }) {
  const { events } = view
  if (!view.run || events.length === 0) {
    return <p className="text-sm text-stone-500 dark:text-stone-400">No Re-scrape events yet. They appear here once a Re-scrape has started.</p>
  }
  return (
    <details className="text-sm text-stone-700 dark:text-stone-300">
      <summary className="cursor-pointer">
        Latest Re-scrape: {latestEventText(view)} <span className="text-stone-400">({events.length} events)</span>
      </summary>
      <ol className="mt-1 max-h-72 space-y-0.5 overflow-y-auto text-xs">
        {events.map((event, index) => (
          <li key={`${index}-${event.type}`}>
            <span className="text-stone-400">{eventTime(event)}</span> {eventText(event)}
          </li>
        ))}
      </ol>
    </details>
  )
}
