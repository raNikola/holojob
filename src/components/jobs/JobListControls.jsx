import Alert from '../ui/Alert'
import Button from '../ui/Button'

const MODES = [{ id: 'active', label: 'Active' }, { id: 'all', label: 'All' }]

/** The Active/All toggle, All's own filters and the notices. All of it is held by the screen in memory: nothing here is saved. */
export default function JobListControls({ mode, onMode, options = [], classes, onClasses, recent, onRecent, notices = [], onRetry, retrying = false }) {
  const toggleClass = (value) => {
    const next = new Set(classes)
    if (!next.delete(value)) next.add(value)
    onClasses(next)
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Which jobs to list" className="inline-flex overflow-hidden rounded-lg border border-stone-300 dark:border-stone-700">
          {MODES.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              aria-pressed={mode === id}
              onClick={() => onMode(id)}
              className={`px-4 py-2 text-sm font-medium ${mode === id ? 'bg-teal-600 text-white' : 'bg-white text-stone-700 hover:bg-stone-50 dark:bg-stone-900 dark:text-stone-300 dark:hover:bg-stone-800'}`}
            >
              {label}
            </button>
          ))}
        </div>
        {mode === 'all' && (
          <label className="flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
            <input type="checkbox" checked={recent} onChange={(e) => onRecent(e.target.checked)} className="rounded border-stone-300 text-teal-600" />
            Seen in the last 14 days
          </label>
        )}
      </div>
      {mode === 'all' && (
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1">
          <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-stone-500">Class (none ticked shows all)</legend>
          {options.map(({ value, label, count }) => (
            <label key={value} className="flex items-center gap-1.5 text-sm text-stone-700 dark:text-stone-300">
              <input type="checkbox" checked={classes.has(value)} onChange={() => toggleClass(value)} className="rounded border-stone-300 text-teal-600" />
              {label} ({count})
            </label>
          ))}
        </fieldset>
      )}
      {notices.map((notice) => (
        <Alert key={notice.text} variant={notice.kind === 'error' ? 'error' : 'info'}>
          <span role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</span>
          {notice.retry && <Button variant="secondary" className="ml-3 !min-h-0 !py-1 !text-xs" disabled={retrying} onClick={onRetry}>Try again</Button>}
        </Alert>
      ))}
    </div>
  )
}
