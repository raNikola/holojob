import { useState } from 'react'
import Badge from '../ui/Badge'
import Card from '../ui/Card'
import CancelRun from './CancelRun'
import { useLiveRun } from '../../modules/activity/useLiveRun.js'
import { CANCEL_REQUESTED_TEXT, currentStepText, elapsedText, liveSourceRows } from '../../modules/activity/liveView.js'
import { formatTime } from '../../modules/activity/runView.js'
import { eventText } from '../../modules/jobs/rescrapeRun.js'

const muted = 'text-stone-500 dark:text-stone-400'

/** The run that is going now (S7c): where it is, its sources as they report, its events, how long it has run, and Cancel for a Re-scrape. */
export default function LiveRunPanel({ run: listed, fetchFn, onFinished, onNotice }) {
  const live = useLiveRun({ runId: listed.runId, fetchFn, onFinished })
  const [asked, setAsked] = useState(false)
  const run = live.run ?? listed
  const rows = liveSourceRows(run, live.events)
  const step = currentStepText(run)
  const elapsed = elapsedText(run, live.receivedAt)
  // The server's flag, or our own request. Either way the run is still going until its record says otherwise.
  const requested = run.cancelRequested || asked

  function answered(answer) {
    if (answer.kind === 'requested') {
      setAsked(true)
      live.refresh()
    } else {
      onNotice?.(answer)
      live.refresh()
    }
  }

  return (
    <Card>
      <section aria-label="The run in progress" className="space-y-3" data-testid="live-run">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className="font-display text-lg font-semibold">{live.finished ? 'This run has finished' : 'A run is in progress'}</h3>
          {!live.finished && <Badge variant="derived">Running</Badge>}
          <span className={`text-sm ${muted}`}>Started {formatTime(run.startedAt)}</span>
          {elapsed && !live.finished && <span className={`text-sm ${muted}`}>{elapsed} (as of the last update)</span>}
          {step && !live.finished && <span className={`text-sm ${muted}`}>{step}</span>}
        </div>

        {requested && !live.finished && <p role="status" className="text-sm font-medium">{CANCEL_REQUESTED_TEXT}</p>}
        {live.finished && <p role="status" className="text-sm">Updating the list…</p>}
        {live.error && (
          <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">
            The live view could not be updated ({live.error}). Trying again in {Math.round(live.retryInMs / 1000)} s. The run itself is not affected.
          </p>
        )}

        {rows.length === 0 ? (
          <p className={`text-sm ${muted}`}>No source has reported yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left text-sm" aria-label="Sources so far">
              <thead className={`text-xs ${muted}`}><tr><th className="pr-3 font-medium">Source</th><th className="pr-3 font-medium">State</th><th className="pr-3 font-medium">Returned</th><th className="font-medium">Collected</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name} className="border-t border-stone-200 dark:border-stone-800">
                    <th scope="row" className="py-1 pr-3 text-left font-medium">{row.name}</th>
                    <td className="py-1 pr-3">{row.reading ? <Badge variant="derived">{row.state}</Badge> : row.state}</td>
                    <td className="py-1 pr-3 tabular-nums">{row.returned}</td>
                    <td className="py-1 tabular-nums">{row.collected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {live.events.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm">{eventText(live.events[live.events.length - 1])} <span className={muted}>({live.events.length} events)</span></summary>
            <ol className="mt-1 max-h-60 space-y-0.5 overflow-y-auto text-xs">
              {live.events.map((event, index) => (
                <li key={`${index}-${event.type}`}><span className={muted}>{event.at ? new Date(event.at).toLocaleTimeString() : ''}</span> {eventText(event)}</li>
              ))}
            </ol>
          </details>
        )}

        {run.canCancel && !live.finished && <CancelRun runId={run.runId} requested={run.cancelRequested} fetchFn={fetchFn} onAnswer={answered} />}
        {!run.canCancel && !live.finished && <p className={`text-xs ${muted}`}>This run was not started by a Re-scrape, so it cannot be cancelled here.</p>}
      </section>
    </Card>
  )
}
