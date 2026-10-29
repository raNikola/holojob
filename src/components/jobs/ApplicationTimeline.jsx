import { timeline } from '../../modules/applications/trackerController'

/** Every event of one application, newest first. Read only: corrections are made in the form above. */
export default function ApplicationTimeline({ app, settings }) {
  const lines = timeline(app, settings)
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-stone-600 dark:text-stone-400">History ({lines.length})</summary>
      <ul className="mt-2 space-y-1 text-stone-700 dark:text-stone-300">
        {lines.map((line) => (
          <li key={line.id}>
            <span className="text-xs text-stone-500">{line.date}</span> <span className="font-medium">{line.title}</span>
            {line.detail ? <span className="text-stone-600 dark:text-stone-400"> · {line.detail}</span> : null}
          </li>
        ))}
      </ul>
    </details>
  )
}
