import { useState } from 'react'
import { parseDescription, truncateDescription } from '../../modules/jobs/descriptionFormat'

const COLLAPSED_CHARS = 600

function Runs({ runs }) {
  return runs.map((r, i) => (r.bold ? <strong key={i} className="font-semibold text-stone-900 dark:text-stone-100">{r.text}</strong> : <span key={i}>{r.text}</span>))
}

/** The ad as formatted blocks: paragraphs, headings, bullet lists, bold. */
export default function JobDescription({ text }) {
  const [expanded, setExpanded] = useState(false)
  if (!text) return null
  const { text: shown, truncated } = expanded ? { text, truncated: false } : truncateDescription(text, COLLAPSED_CHARS)
  const canExpand = expanded || truncated

  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-500">Description</h4>
      <div className="mt-2 space-y-3 text-sm text-stone-700 dark:text-stone-300">
        {parseDescription(shown).map((b, i) => {
          if (b.type === 'h') return <h5 key={i} className="pt-1 text-sm font-semibold text-stone-900 dark:text-stone-100"><Runs runs={b.runs} /></h5>
          if (b.type === 'ul' || b.type === 'ol') {
            const List = b.type
            return (
              <List key={i} className={`space-y-1 pl-5 ${b.type === 'ul' ? 'list-disc' : 'list-decimal'}`}>
                {b.items.map((runs, j) => <li key={j}><Runs runs={runs} /></li>)}
              </List>
            )
          }
          return <p key={i}><Runs runs={b.runs} /></p>
        })}
      </div>
      {canExpand && (
        <button type="button" className="mt-2 text-xs text-teal-600" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}
