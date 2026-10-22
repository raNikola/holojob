import Badge from '../ui/Badge'

const FIT_VARIANT = { strong: 'high', good: 'default', partial: 'medium', poor: 'warn' }

const STATUS = {
  met: { mark: '✓', label: 'met', className: 'text-emerald-700 dark:text-emerald-400' },
  partly_met: { mark: '◐', label: 'partly met', className: 'text-amber-700 dark:text-amber-400' },
  not_met: { mark: '✗', label: 'not met', className: 'text-red-700 dark:text-red-400' },
  unclear: { mark: '?', label: 'unclear', className: 'text-stone-500' },
}

export const isFitReason = (reason) => reason.startsWith('LLM fit:')

function Heading({ children, className = 'text-stone-500' }) {
  return <h5 className={`mb-1 text-xs font-semibold uppercase tracking-wide ${className}`}>{children}</h5>
}

export default function FitJudgementSection({ fit }) {
  if (!fit) return null

  if (fit.error) {
    return (
      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Fit judgement</h4>
        <p className="text-sm text-stone-600 dark:text-stone-400">Judge call failed: {fit.error} (local score kept)</p>
      </div>
    )
  }

  const adjustment = fit.adjustment ?? 0
  const signed = adjustment > 0 ? `+${adjustment}` : String(adjustment)

  return (
    <div className="space-y-3 rounded-lg border border-stone-200 p-3 dark:border-stone-800">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-500">Fit judgement</h4>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={FIT_VARIANT[fit.fit] || 'default'}>{fit.fit}</Badge>
        <span className="text-stone-700 dark:text-stone-300">
          {signed}
          {fit.localScore != null && <> (local {fit.localScore} → {fit.localScore + adjustment})</>}
        </span>
      </div>
      {fit.fitReason && <p className="text-sm text-stone-700 dark:text-stone-300">{fit.fitReason}</p>}

      {fit.requirements?.length > 0 && (
        <div>
          <Heading>Requirements</Heading>
          <ul className="space-y-1.5">
            {fit.requirements.map((r) => {
              const s = STATUS[r.status] || STATUS.unclear
              return (
                <li key={r.requirement} className="text-sm">
                  <span className={`mr-1.5 font-semibold ${s.className}`} title={s.label} aria-label={s.label}>{s.mark}</span>
                  <span className="text-stone-800 dark:text-stone-200">{r.requirement}</span>
                  {r.evidence && <span className="block pl-5 text-xs text-stone-500">{r.evidence}</span>}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {fit.missing?.length > 0 && (
        <div>
          <Heading>Missing</Heading>
          <div className="flex flex-wrap gap-1.5">
            {fit.missing.map((m) => (
              <span key={m} className="rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">{m}</span>
            ))}
          </div>
        </div>
      )}

      {fit.dealbreakers?.length > 0 && (
        <div>
          <Heading className="text-red-600">Dealbreakers</Heading>
          <ul className="list-inside list-disc text-sm text-red-700 dark:text-red-400">
            {fit.dealbreakers.map((d) => <li key={d}>{d}</li>)}
          </ul>
        </div>
      )}

      <p className="border-t border-stone-100 pt-2 text-xs text-stone-500 dark:border-stone-800">
        Judged by {fit.provider}{fit.model ? ` ${fit.model}` : ''}{fit.fromCache ? ' · from cache' : ''}
      </p>
    </div>
  )
}
