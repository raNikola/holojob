import { X } from 'lucide-react'
import JobDetailBody from './JobDetailBody'

export default function JobDetailDrawer({
  job,
  onClose,
  apiAvailable,
  onJobUpdated,
  onStatusChange,
}) {
  if (!job) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" className="absolute inset-0 bg-black/40" onClick={onClose} aria-label="Close" />
      <aside className="panel-text-up relative flex h-full w-full max-w-[75rem] flex-col overflow-y-auto bg-white shadow-xl dark:bg-stone-950">
        <div className="sticky top-0 flex items-start justify-between border-b border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-950">
          <div>
            <h2 className="font-display text-lg font-semibold text-stone-900 dark:text-stone-100">{job.title}</h2>
            <p className="text-sm text-stone-600 dark:text-stone-400">{job.company}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-stone-100 dark:hover:bg-stone-800">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4">
          <JobDetailBody job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} onStatusChange={onStatusChange} />
        </div>
      </aside>
    </div>
  )
}
