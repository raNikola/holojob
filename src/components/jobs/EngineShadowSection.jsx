import Badge from '../ui/Badge'
import {
  BUCKET,
  ENGINE_LABEL_VARIANT,
  GATE_NAME,
  GATE_RESULT,
  STATUS,
  STRENGTH,
  engineSummary,
  hasEngineResult,
} from '../../modules/jobs/engineShadow'

const SHADOW_BOX = 'rounded-lg border border-dashed border-violet-300 bg-violet-50/40 dark:border-violet-700 dark:bg-violet-950/20'

function ShadowTag() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full border border-dashed border-violet-400 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 dark:border-violet-600 dark:text-violet-300">
      new engine (shadow)
    </span>
  )
}

/** Compact, next to matchScore in the job list; the full breakdown is in the drawer. */
export function EngineShadowBadge({ shadow }) {
  if (!shadow) return null
  const title = `${engineSummary(shadow)}. Open the job for the breakdown.`
  if (!hasEngineResult(shadow)) {
    return <span title={title} className="text-[10px] text-violet-700 dark:text-violet-300">shadow: failed</span>
  }
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-md border border-dashed border-violet-300 px-1.5 py-0.5 text-[11px] text-violet-800 dark:border-violet-700 dark:text-violet-200">
      <span className="font-semibold">shadow</span>
      <span className="tabular-nums">{shadow.fit}</span>
      <span>{shadow.label}</span>
    </span>
  )
}

function Heading({ children }) {
  return <h5 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">{children}</h5>
}

function Requirement({ r }) {
  const s = STATUS[r.status] || STATUS.UNKNOWN
  return (
    <li className="text-sm">
      <div>
        <span className={`mr-1.5 font-semibold ${s.className}`} title={r.status} aria-label={r.status}>{s.mark}</span>
        <span className="text-stone-800 dark:text-stone-200">{r.text}</span>
        <span className="ml-2 text-xs text-stone-500">
          {r.status} · {r.importance} · strength {r.strength} ({STRENGTH[r.strength] ?? '?'})
          {r.provisional ? ' · provisional id' : ''}
        </span>
      </div>
      <div className="space-y-0.5 pl-5 text-xs text-stone-500">
        <div>Ad: “{r.postingQuote}”</div>
        {r.evidenceQuote && (
          <div>
            Evidence{r.evidenceId ? ` (${r.evidenceId})` : ''}: “{r.evidenceQuote}”
            <span className={r.quoteVerified ? 'ml-1 text-emerald-700 dark:text-emerald-400' : 'ml-1 text-red-700 dark:text-red-400'}>
              {r.quoteVerified ? 'quote verified' : 'quote not found, downgraded'}
            </span>
          </div>
        )}
      </div>
    </li>
  )
}

const STATUS_ORDER = { MISSING: 0, UNKNOWN: 1, PARTIAL: 2, MET: 3 }
const IMPORTANCE_ORDER = { must: 0, preferred: 1, nice: 2 }

/** The drawer's read-only view of job.engineShadow: verdict, gates, every requirement. */
export default function EngineShadowSection({ shadow }) {
  if (!shadow) return null

  if (!hasEngineResult(shadow)) {
    return (
      <div className={`space-y-1 p-3 ${SHADOW_BOX}`}>
        <ShadowTag />
        <p className="text-sm text-stone-600 dark:text-stone-400">Engine call failed: {shadow.error} (no Fit for this job)</p>
      </div>
    )
  }

  const c = shadow.counts || {}
  const requirements = [...(shadow.requirements || [])].sort((a, b) =>
    (IMPORTANCE_ORDER[a.importance] ?? 3) - (IMPORTANCE_ORDER[b.importance] ?? 3)
    || (STATUS_ORDER[a.status] ?? 4) - (STATUS_ORDER[b.status] ?? 4))
  const bucket = BUCKET[shadow.bucket] || { label: shadow.bucket, variant: 'default' }

  return (
    <div className={`space-y-3 p-3 ${SHADOW_BOX}`}>
      <div className="flex flex-wrap items-center gap-2">
        <ShadowTag />
        <span className="text-xs text-stone-500">Read only: does not change the score, ranking or filters above.</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={ENGINE_LABEL_VARIANT[shadow.label] || 'default'}>{shadow.labelText || shadow.label}</Badge>
        <span className="font-semibold tabular-nums text-stone-900 dark:text-stone-100">Fit {shadow.fit}</span>
        <span className="text-stone-600 dark:text-stone-400">confidence {Number(shadow.confidence).toFixed(2)}</span>
        <Badge variant={bucket.variant}>{bucket.label}</Badge>
        {shadow.caps?.length > 0 && <span className="text-xs text-amber-700 dark:text-amber-400">capped: {shadow.caps.join(', ')}</span>}
      </div>

      <p className="text-xs text-stone-600 dark:text-stone-400">
        Musts met {c.mustMet ?? 0}/{c.mustTotal ?? 0} · preferred met {c.preferredMet ?? 0}/{c.preferredTotal ?? 0}
        {' '}· unknown {c.unknown ?? 0} · blockers {c.blockers ?? 0}
      </p>

      <div>
        <Heading>Gates</Heading>
        <ul className="space-y-1">
          {(shadow.gates || []).map((g) => {
            const r = GATE_RESULT[g.result] || GATE_RESULT.unknown
            return (
              <li key={g.gate} className="text-sm">
                <span className={`mr-1.5 font-semibold ${r.className}`} aria-label={g.result}>{r.mark}</span>
                <span className="text-stone-800 dark:text-stone-200">{GATE_NAME[g.gate] || g.gate}</span>
                <span className="ml-2 text-xs text-stone-500">{g.result}</span>
                {g.quote && <span className="block pl-5 text-xs text-stone-500">Ad: “{g.quote}”</span>}
              </li>
            )
          })}
        </ul>
      </div>

      <details open={requirements.length <= 12}>
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-stone-500">
          Requirements ({requirements.length})
        </summary>
        <ul className="mt-2 space-y-2">
          {requirements.map((r, i) => <Requirement key={`${r.id}-${i}`} r={r} />)}
        </ul>
      </details>

      {shadow.questions?.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-stone-500">
            Questions ({shadow.questions.length})
          </summary>
          <ul className="mt-2 list-inside list-disc text-sm text-stone-700 dark:text-stone-300">
            {shadow.questions.map((q) => <li key={q.competencyId}>{q.question}</li>)}
          </ul>
        </details>
      )}

      {shadow.warnings?.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs text-stone-500">Warnings ({shadow.warnings.length})</summary>
          <ul className="mt-1 list-inside list-disc text-xs text-stone-500">
            {shadow.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </details>
      )}

      <p className="border-t border-violet-200 pt-2 text-xs text-stone-500 dark:border-violet-800">
        Engine {shadow.engineVersion} · prompts {shadow.promptVersion}
        {shadow.provider ? ` · matched by ${shadow.provider}${shadow.model ? ` ${shadow.model}` : ''}` : ''}
        {shadow.fromCache ? ' · from cache' : ''}
      </p>
    </div>
  )
}
