import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ExternalLink, Loader2 } from 'lucide-react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Card from '../ui/Card'
import {
  FUNCTION_OPTIONS, OVERALL_OPTIONS, REQUIREMENT_OPTIONS, fetchReview, isComplete, nextUnreviewed, saveJudgment, startingJudgment,
} from '../../modules/calibration/calibrationClient'

const labelOf = (options, value) => options.find((o) => o.value === value)?.label ?? 'Not set'

function Choice({ legend, hint, options, value, onChange }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium text-stone-900 dark:text-stone-50">{legend}</legend>
      <p className="text-xs text-stone-500 dark:text-stone-400">{hint}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={value === o.value}
            onClick={() => onChange(o.value)}
            className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${value === o.value
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

function Suggestion({ proposal }) {
  if (!proposal) {
    return <p className="text-sm text-stone-500 dark:text-stone-400">There is no AI suggestion for this ad. Please give your own judgment.</p>
  }
  return (
    <div className="space-y-2 text-sm text-stone-800 dark:text-stone-100">
      <p><span className="font-medium">Is it my kind of work?</span> {labelOf(FUNCTION_OPTIONS, proposal.functionFit)}</p>
      <p><span className="font-medium">Do I meet what is required?</span> {labelOf(REQUIREMENT_OPTIONS, proposal.hardRequirements)}</p>
      <p><span className="font-medium">Would I apply?</span> {labelOf(OVERALL_OPTIONS, proposal.overall)}</p>
      {proposal.reason && <p className="text-stone-600 dark:text-stone-300">{proposal.reason}</p>}
      <p className="text-xs text-stone-500 dark:text-stone-400">
        The AI is {proposal.confidence ?? 'not'} sure.
        {proposal.missingInformation?.length > 0 && ` It was missing: ${proposal.missingInformation.join('; ')}.`}
      </p>
    </div>
  )
}

/** The temporary calibration screen. Reached only by the direct route; the system's own score is never shown here. */
export default function CalibrationReview({ fetchFn }) {
  const [items, setItems] = useState(null)
  const [index, setIndex] = useState(0)
  const [draft, setDraft] = useState(null)
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const open = useCallback((list, at) => {
    setIndex(at)
    setDraft(startingJudgment(list[at]))
    setTouched(false)
    setError(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchReview(fetchFn).then((review) => {
      if (cancelled) return
      setItems(review.items)
      const first = nextUnreviewed(review.items, 0)
      open(review.items, first === -1 ? 0 : first)
    }).catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [fetchFn, open])

  const reviewed = useMemo(() => (items ?? []).filter((i) => i.label).length, [items])
  const item = items?.[index]

  const choose = (field) => (value) => {
    setDraft((d) => ({ ...d, [field]: value }))
    setTouched(true)
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const { label } = await saveJudgment({ jobId: item.jobId, ...draft }, fetchFn)
      const next = items.map((i, n) => (n === index ? { ...i, label } : i))
      setItems(next)
      const after = nextUnreviewed(next, index + 1)
      if (after === -1) open(next, index)
      else open(next, after)
    } catch (e) {
      setError(`Your judgment was not saved: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (error && !items) {
    return <div className="mx-auto max-w-3xl p-6"><Alert variant="error" title="The review cannot be opened">{error}</Alert></div>
  }
  if (!items) {
    return <div className="mx-auto flex max-w-3xl items-center gap-2 p-6 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading</div>
  }

  const allDone = reviewed === items.length
  const saved = Boolean(item.label)
  const confirmsSuggestion = !saved && item.proposal && !touched
  const buttonLabel = confirmsSuggestion ? 'Confirm the AI suggestion' : saved ? 'Save my change' : 'Save my judgment'

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-stone-900 dark:text-stone-50">Ad review</h1>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Check each ad. Your answers are the reference; the AI suggestion is only a starting point. Everything is saved as you go.
        </p>
        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 rounded-full bg-stone-200 dark:bg-stone-800" role="progressbar" aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={reviewed}>
            <div className="h-2 rounded-full bg-teal-600" style={{ width: `${(reviewed / items.length) * 100}%` }} />
          </div>
          <span className="text-sm text-stone-700 dark:text-stone-200" data-testid="progress">{reviewed} of {items.length} reviewed</span>
        </div>
      </header>

      {allDone && <Alert variant="success" title="All ads are reviewed">You can still go back and change any answer.</Alert>}

      <Card>
        <div className="space-y-1">
          <h2 className="font-display text-lg font-semibold text-stone-900 dark:text-stone-50">{item.title}</h2>
          <p className="text-sm text-stone-600 dark:text-stone-300">{[item.company, item.location, item.site].filter(Boolean).join(' · ')}</p>
          {item.jobUrl && (
            <a href={item.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-teal-700 hover:underline dark:text-teal-400">
              Open the original ad <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
        <div className="mt-4 max-h-[28rem] overflow-y-auto whitespace-pre-wrap rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-800 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-100" data-testid="description">
          {item.description || 'This ad has no text.'}
        </div>
      </Card>

      <Card title="AI suggestion" description="A proposal to check, not an answer.">
        <Suggestion proposal={item.proposal} />
      </Card>

      <Card title="Your judgment" description={saved ? 'Saved. You can change it.' : undefined}>
        <div className="space-y-5">
          <Choice legend="Is it my kind of work?" hint="The day-to-day work, not just the title." options={FUNCTION_OPTIONS} value={draft.functionFit} onChange={choose('functionFit')} />
          <Choice legend="Do I meet what is required?" hint="The things the ad says you must have." options={REQUIREMENT_OPTIONS} value={draft.hardRequirements} onChange={choose('hardRequirements')} />
          <Choice legend="Would I apply?" hint="Overall, as an option for me." options={OVERALL_OPTIONS} value={draft.overall} onChange={choose('overall')} />
          {error && <Alert variant="error">{error}</Alert>}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={save} disabled={saving || !isComplete(draft) || (saved && !touched)}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} {buttonLabel}
            </Button>
            <Button variant="ghost" disabled={index === 0} onClick={() => open(items, index - 1)}>Previous ad</Button>
            <Button variant="ghost" disabled={index === items.length - 1} onClick={() => open(items, index + 1)}>Next ad</Button>
            <span className="text-xs text-stone-500 dark:text-stone-400">Ad {index + 1} of {items.length}</span>
          </div>
        </div>
      </Card>
    </div>
  )
}
