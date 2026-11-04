import { eventText, latestEventText } from '../../modules/jobs/rescrapeRun.js'

function eventTime(event) {
  const date = new Date(event.at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString()
}

/** The latest event of the server's Re-scrape, every event behind an expander, and what a dead run or an unfinished save left behind. */
export default function RescrapeProgress({ view }) {
  if (!view.run) return null
  const { incompleteCommit: commit, events } = view
  return (
    <div role="status" className="w-full space-y-1 text-xs text-stone-600 dark:text-stone-400">
      {view.run.status === 'interrupted' && (
        <p className="text-amber-700 dark:text-amber-400">The last run was interrupted before it finished. It is not resumed: start it again when you want fresh jobs.</p>
      )}
      {view.run.status === 'cancelled' && (
        <p className="text-amber-700 dark:text-amber-400">
          {view.run.cancel?.outcome === 'stopped_nothing_imported'
            ? 'The last run was cancelled and had to be stopped hard: nothing was imported and no job changed. Scoring was skipped.'
            : 'The last run was cancelled. The ads collected so far were imported and held: nothing was closed or marked absent, and the run does not count as a finished check. Scoring was skipped.'}
        </p>
      )}
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
      {events.length > 0 && (
        <details>
          <summary className="cursor-pointer">
            {latestEventText(view)} <span className="text-stone-400">({events.length} events)</span>
          </summary>
          <ol className="mt-1 max-h-60 space-y-0.5 overflow-y-auto">
            {events.map((event, index) => (
              <li key={`${index}-${event.type}`}>
                <span className="text-stone-400">{eventTime(event)}</span> {eventText(event)}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
