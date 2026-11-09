import Badge from '../ui/Badge'
import Card from '../ui/Card'
import { allApplicationRecords } from '../../modules/applications/trackingView'

const FROM_LABEL = { scored_jobs: 'scored list', job_history: 'job history', browser: 'browser copy', csv: 'CSV', manual: 'typed in' }

function snapshotText({ capturedFrom, capturedAfterApply, descriptionMissing }) {
  const parts = [FROM_LABEL[capturedFrom] ?? 'unknown source', capturedAfterApply ? 'taken after applying' : 'taken at apply time']
  if (descriptionMissing) parts.push('no ad text')
  return parts.join(', ')
}

/** Every record in the tracker, voided ones too, read-only. A voided one opens on Job Details, where Restore is. */
export default function ApplicationRecordsList({ store, onOpenJob }) {
  const records = allApplicationRecords(store)
  return (
    <Card title="All records">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Every application on the server, whether or not its ad is still listed, including voided ones. Voided records are not counted anywhere else.
      </p>
      {records.length === 0 ? (
        <p className="text-sm text-stone-600 dark:text-stone-400">No applications recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-stone-200 text-xs uppercase tracking-wide text-stone-500 dark:border-stone-700">
                <th className="pb-3 pr-4 font-medium">Company</th>
                <th className="pb-3 pr-4 font-medium">Role</th>
                <th className="pb-3 pr-4 font-medium">Applied</th>
                <th className="pb-3 pr-4 font-medium">State</th>
                <th className="pb-3 font-medium">Ad snapshot</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr
                  key={r.id}
                  className={`border-b border-stone-100 dark:border-stone-800 ${r.jobId ? 'cursor-pointer hover:bg-stone-50 dark:hover:bg-stone-900/50' : ''}`}
                  onClick={r.jobId ? () => onOpenJob(r.jobId) : undefined}
                >
                  <td className="py-3 pr-4 font-medium text-stone-900 dark:text-stone-100">{r.company || '—'}</td>
                  <td className="py-3 pr-4 text-stone-700 dark:text-stone-300">{r.title || '—'}</td>
                  <td className="py-3 pr-4">{r.appliedDate || '—'}</td>
                  <td className="py-3 pr-4">{r.voided ? <Badge variant="low">Voided</Badge> : <Badge variant="medium">Active</Badge>}</td>
                  <td className="py-3 text-xs text-stone-600 dark:text-stone-400">{snapshotText(r.snapshot)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
