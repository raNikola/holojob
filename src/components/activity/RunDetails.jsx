import Badge from '../ui/Badge'
import {
  NOT_RECORDED, NUMBER_HELP, PROOF_HELP, SOURCE_NEW_NOTE, SOURCE_STATUS_TONES, filterReasonText, formatDuration, formatTime, ledgerText, proofView, savedText,
  scoringText, show, sourceStatusLabel, stagingText,
} from '../../modules/activity/runView.js'

const muted = 'text-stone-500 dark:text-stone-400'

function NumberCell({ label, value, help }) {
  return (
    <div>
      <dt className="text-xs font-medium text-stone-700 dark:text-stone-300">{label}</dt>
      <dd className={value === NOT_RECORDED ? `text-sm ${muted}` : 'text-sm font-semibold text-stone-900 dark:text-stone-50'}>{value}</dd>
      <dd className={`text-xs ${muted}`}>{help}</dd>
    </div>
  )
}

function RunNumbers({ run }) {
  const help = Object.fromEntries(NUMBER_HELP)
  const { counts } = run
  return (
    <div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Numbers for this run">
        <NumberCell label="Returned" value={show(counts.returned)} help={help.Returned} />
        <NumberCell label="Filtered out" value={show(counts.filteredOut)} help={help['Filtered out']} />
        <NumberCell label="Collected" value={show(counts.collected)} help={help.Collected} />
        <NumberCell label="Saved" value={show(counts.saved)} help={help.Saved} />
        <NumberCell label="New" value={show(counts.new)} help={help.New} />
        <NumberCell label="Refreshed" value={show(counts.refreshed)} help={help.Refreshed} />
      </dl>
      <p className="mt-2 text-sm font-medium text-stone-800 dark:text-stone-200">{savedText(run)}</p>
      {run.import && (run.import.duplicatesRemoved !== null || run.import.rejected !== null) && (
        <p className={`text-xs ${muted}`}>
          Duplicates merged: {show(run.import.duplicatesRemoved)}. Cross-posts merged: {show(run.import.crosspostsMerged)}. Ads rejected as not whole: {show(run.import.rejected)}.
        </p>
      )}
    </div>
  )
}

function Boards({ proof, failedNames }) {
  const boards = proof.boards ?? []
  const open = boards.filter((board) => board.state !== 'proven')
  const proven = boards.length - open.length
  if (!boards.length && !failedNames.length) return null
  return (
    <div className="mt-1 text-xs">
      {boards.length > 0 && <p className={muted}>{proven} of {boards.length} boards proven{open.length ? '. Boards that are not:' : '.'}</p>}
      {open.length > 0 && (
        <ul className="ml-4 list-disc">
          {open.slice(0, 20).map((board) => (
            <li key={board.board}>
              <span className="font-medium">{board.board}</span>: {proofView(board).lines.join('; ') || 'Not proven'}
              {board.detail ? ` (${board.detail})` : ''}
            </li>
          ))}
          {open.length > 20 && <li>and {open.length - 20} more</li>}
        </ul>
      )}
      {failedNames.length > 0 && <p>Boards that failed: {failedNames.slice(0, 20).join(', ')}{failedNames.length > 20 ? ` and ${failedNames.length - 20} more` : ''}</p>}
    </div>
  )
}

function SourceRow({ source }) {
  const proof = proofView(source.proof)
  const reasons = filterReasonText(source.filterReasons)
  return (
    <tr className="border-t border-stone-200 align-top dark:border-stone-800">
      <th scope="row" className="py-2 pr-3 text-left font-medium">{source.name}</th>
      <td className="py-2 pr-3"><Badge variant={SOURCE_STATUS_TONES[source.status] ?? 'low'}>{sourceStatusLabel(source.status)}</Badge></td>
      <td className="py-2 pr-3 tabular-nums">{show(source.returned)}</td>
      <td className="py-2 pr-3">
        <span className="tabular-nums">{show(source.filteredOut)}</span>
        {reasons && <div className={`text-xs ${muted}`}>{reasons}</div>}
      </td>
      <td className="py-2 pr-3 tabular-nums">{show(source.collected)}</td>
      <td className="py-2 pr-3 tabular-nums">{show(source.new)}</td>
      <td className="min-w-[14rem] py-2 pr-3">
        <Badge variant={proof.tone}>{proof.label}</Badge>
        {proof.lines.map((line) => <div key={line} className="mt-1 text-xs">{line}</div>)}
        <Boards proof={source.proof} failedNames={source.boardsFailed ?? []} />
      </td>
      <td className="min-w-[10rem] py-2 pr-3 text-xs">
        {source.error && <div>Error: {source.error}</div>}
        {source.skipReason && <div>Skipped: {source.skipReason}</div>}
        {!source.error && !source.skipReason && <span className={muted}>None</span>}
      </td>
      <td className="py-2 text-xs">
        <div>{source.startedAt ? formatTime(source.startedAt) : NOT_RECORDED}</div>
        <div className={muted}>{source.durationSeconds === null ? '' : formatDuration(source.durationSeconds)}</div>
      </td>
    </tr>
  )
}

export default function RunDetails({ run }) {
  return (
    <div className="mt-3 space-y-4 border-t border-stone-200 pt-3 text-sm dark:border-stone-800" data-testid="run-details">
      <RunNumbers run={run} />

      <div>
        <h4 className="font-medium">Sources</h4>
        {run.sources.length === 0 ? (
          <p className={muted}>No source is recorded for this run.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="mt-1 w-full min-w-[56rem] text-left text-sm">
                <thead className={`text-xs ${muted}`}>
                  <tr>
                    <th className="pr-3 font-medium">Source</th><th className="pr-3 font-medium">Status</th><th className="pr-3 font-medium">Returned</th>
                    <th className="pr-3 font-medium">Filtered out</th><th className="pr-3 font-medium">Collected</th><th className="pr-3 font-medium">New</th>
                    <th className="pr-3 font-medium">Proof</th><th className="pr-3 font-medium">Error or skip reason</th><th className="font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>{run.sources.map((source) => <SourceRow key={source.name} source={source} />)}</tbody>
              </table>
            </div>
            <p className={`mt-1 text-xs ${muted}`}>{SOURCE_NEW_NOTE}</p>
            <p className={`text-xs ${muted}`}>{PROOF_HELP}</p>
          </>
        )}
      </div>

      <dl className="grid gap-3 sm:grid-cols-3">
        <div><dt className="text-xs font-medium">Ledger effect</dt><dd>{ledgerText(run)}</dd></div>
        <div><dt className="text-xs font-medium">Scoring</dt><dd>{scoringText(run)}</dd></div>
        <div><dt className="text-xs font-medium">Staging</dt><dd>{stagingText(run)}</dd></div>
      </dl>

      <div>
        <h4 className="font-medium">Issues</h4>
        {run.issuesCount === 0 ? (
          <p className={muted}>No errors or warnings.</p>
        ) : (
          <>
            <ul className="mt-1 space-y-1">
              {run.issues.map((issue, index) => (
                <li key={index} className="flex gap-2">
                  <Badge variant={issue.level === 'error' ? 'warn' : 'medium'}>{issue.level === 'error' ? 'Error' : 'Warning'}</Badge>
                  <span>{issue.source ? `${issue.source}: ` : ''}{issue.message}</span>
                </li>
              ))}
            </ul>
            {run.issuesCount > run.issues.length && <p className={`text-xs ${muted}`}>Showing {run.issues.length} of {run.issuesCount}.</p>}
          </>
        )}
      </div>
    </div>
  )
}
