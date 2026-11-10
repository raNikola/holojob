import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ExternalLink, Loader2 } from 'lucide-react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Card from '../ui/Card'
import {
  IS_MUST_OPTIONS, KIND_TEXT, MEETS_OPTIONS, VERDICT_TEXT, fetchMusts, isComplete, nextUnanswered, saveMustAnswer,
} from '../../modules/calibration/mustClient'

const labelOf = (options, value) => options.find((o) => o.value === value)?.label ?? 'Not set'
const EMPTY = { isMust: null, meets: null }

function Choice({ legend, hint, options, value, onChange, disabled }) {
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium text-stone-900 dark:text-stone-50">{legend}</legend>
      <p className="text-xs text-stone-500 dark:text-stone-400">{hint}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${value === o.value
              ? 'border-teal-600 bg-teal-600 text-white dark:border-teal-500 dark:bg-teal-500'
              : 'border-stone-200 bg-white text-stone-700 hover:bg-stone-50 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200 dark:hover:bg-stone-800'}`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  )
}

/** What the engine said, shown only after the answer is saved. */
function Reveal({ reveal }) {
  return (
    <div className="space-y-2 text-sm text-stone-800 dark:text-stone-100" data-testid="reveal">
      <p><span className="font-medium">The engine says:</span> {VERDICT_TEXT[reveal.status] ?? reveal.status}</p>
      {reveal.strength !== null && <p className="text-stone-600 dark:text-stone-300">Evidence strength {reveal.strength} of 4.</p>}
      {reveal.evidenceQuote
        ? <p className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-stone-700 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-200">{reveal.evidenceQuote}</p>
        : <p className="text-stone-500 dark:text-stone-400">The engine quoted no CV evidence for this.</p>}
    </div>
  )
}

/** The temporary must-have review. Direct route only. Blind first: the engine's verdict comes back with your saved answer. */
export default function MustReview({ fetchFn }) {
  const [state, setState] = useState(null)
  const [index, setIndex] = useState(0)
  const [draft, setDraft] = useState(EMPTY)
  const [editing, setEditing] = useState(false)
  const [showAd, setShowAd] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const open = useCallback((at, items) => {
    setIndex(at)
    const label = items[at].label
    setDraft(label ? { isMust: label.final.isMust, meets: label.final.meets } : EMPTY)
    setEditing(false)
    setShowAd(false)
    setError(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchMusts(fetchFn).then((data) => {
      if (cancelled) return
      setState(data)
      const first = nextUnanswered(data.items, 0)
      open(first === -1 ? 0 : first, data.items)
    }).catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [fetchFn, open])

  const items = state?.items
  const answered = useMemo(() => (items ?? []).filter((i) => i.label).length, [items])
  const item = items?.[index]

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const { label, reveal } = await saveMustAnswer({ itemId: item.itemId, ...draft }, fetchFn)
      const next = items.map((i, n) => (n === index ? { ...i, label, reveal } : i))
      setState({ ...state, items: next })
      setEditing(false)
    } catch (e) {
      setError(`Your answer was not saved: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (error && !state) {
    return <div className="mx-auto max-w-3xl p-6"><Alert variant="error" title="The review cannot be opened">{error}</Alert></div>
  }
  if (!state) {
    return <div className="mx-auto flex max-w-3xl items-center gap-2 p-6 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading</div>
  }

  const ad = state.ads[item.jobId]
  const saved = Boolean(item.label)
  const locked = saved && !editing
  const goNext = () => {
    const after = nextUnanswered(items, index + 1)
    open(after === -1 ? Math.min(index + 1, items.length - 1) : after, items)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-stone-900 dark:text-stone-50">Requirement review</h1>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          For each line, answer both questions first. Then you see what the engine said. Your answers are the reference. Everything is saved as you go.
        </p>
        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 rounded-full bg-stone-200 dark:bg-stone-800" role="progressbar" aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={answered}>
            <div className="h-2 rounded-full bg-teal-600" style={{ width: `${(answered / items.length) * 100}%` }} />
          </div>
          <span className="text-sm text-stone-700 dark:text-stone-200" data-testid="progress">{answered} of {items.length} answered</span>
        </div>
      </header>

      {answered === items.length && <Alert variant="success" title="All lines are answered">You can still go back and look at any line.</Alert>}

      <Card>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-teal-700 dark:text-teal-400">{KIND_TEXT[item.kind] ?? item.kind}</p>
          <h2 className="font-display text-lg font-semibold text-stone-900 dark:text-stone-50" data-testid="requirement">{item.text}</h2>
          {item.postingQuote && <p className="text-sm text-stone-600 dark:text-stone-300">The ad says: <span className="italic">{item.postingQuote}</span></p>}
          {ad && <p className="text-sm text-stone-500 dark:text-stone-400">{[ad.title, ad.company].filter(Boolean).join(' · ')}</p>}
          {ad?.jobUrl && (
            <a href={ad.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-teal-700 hover:underline dark:text-teal-400">
              Open the original ad <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {ad?.description && (
            <div>
              <button type="button" className="text-sm text-teal-700 hover:underline dark:text-teal-400" onClick={() => setShowAd(!showAd)}>
                {showAd ? 'Hide the full ad' : 'Show the full ad'}
              </button>
              {showAd && (
                <div className="mt-2 max-h-80 overflow-y-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-800 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-100" data-testid="description">
                  {ad.description}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      <Card title="Your answer" description={locked ? 'Saved.' : saved ? 'A change is recorded as made after seeing the engine.' : 'Answer before you see the engine.'}>
        <div className="space-y-5">
          <Choice legend="Is this really a must?" hint="Would the employer turn you down without it?" options={IS_MUST_OPTIONS} value={draft.isMust} onChange={(v) => setDraft({ ...draft, isMust: v })} disabled={locked} />
          <Choice legend="Do I meet it?" hint="From what you have actually done." options={MEETS_OPTIONS} value={draft.meets} onChange={(v) => setDraft({ ...draft, meets: v })} disabled={locked} />
          {error && <Alert variant="error">{error}</Alert>}
          <div className="flex flex-wrap items-center gap-3">
            {!locked && (
              <Button onClick={save} disabled={saving || !isComplete(draft)}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} {saved ? 'Save my change' : 'Save and show the engine'}
              </Button>
            )}
            {locked && <Button variant="ghost" onClick={() => setEditing(true)}>Change my answer</Button>}
            {locked && <Button onClick={goNext}>Next line</Button>}
            <Button variant="ghost" disabled={index === 0} onClick={() => open(index - 1, items)}>Previous</Button>
            <span className="text-xs text-stone-500 dark:text-stone-400">Line {index + 1} of {items.length}</span>
          </div>
          {saved && item.label.changedAfterReveal && (
            <p className="text-xs text-stone-500 dark:text-stone-400">
              Your first answer ({labelOf(IS_MUST_OPTIONS, item.label.first.isMust)}; {labelOf(MEETS_OPTIONS, item.label.first.meets)}) is kept for the report.
            </p>
          )}
        </div>
      </Card>

      {saved && item.reveal && (
        <Card title="The engine" description="Shown because you have answered.">
          <Reveal reveal={item.reveal} />
        </Card>
      )}
    </div>
  )
}
