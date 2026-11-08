import { ExternalLink } from 'lucide-react'
import Badge from '../ui/Badge'
import FitScore from './FitScore'
import { scoreRowChips } from '../../modules/jobs/fitScore'
import JobTailorActions from './JobTailorActions'
import ApplicationTrackerPanel from './ApplicationTrackerPanel'
import JobAIToolsPanel from '../ai/JobAIToolsPanel'
import RelatedContactsPanel from '../outreach/RelatedContactsPanel'
import { hasMatchScores, isInsufficientData } from '../../modules/jobs/matchScore'
import { getJobProvider } from '../../modules/jobs/jobFilters'
import { isCapReason } from '../../modules/jobs/workAuthorization'
import AuthorizationBadge from './AuthorizationBadge'
import JobDescription from './JobDescription'
import { formatSeen, historyBadges } from '../../modules/jobs/jobHistory'
import { formatMonthlyEur, salaryBadges } from '../../modules/jobs/jobSalary'
import FitJudgementSection, { isFitReason } from './FitJudgementSection'
import ManualJobSection from './ManualJobSection'
import { jobStatusLabel } from '../../modules/jobs/manualJob'
import EngineShadowSection, { EngineShadowBadge } from './EngineShadowSection'

const DIMENSION_LABELS = {
  roleMatch: 'Role',
  skillMatch: 'Skill',
  industryMatch: 'Industry',
  experienceMatch: 'Experience',
  locationMatch: 'Location',
  cultureMatch: 'Culture',
}

export function ScoreBreakdown({ breakdown }) {
  if (!breakdown) return null
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-stone-500">Score breakdown</h4>
      {Object.entries(breakdown).map(([key, val]) => (
        <div key={key}>
          <div className="mb-1 flex justify-between text-xs">
            <span>{DIMENSION_LABELS[key] || key}</span>
            <span className="text-stone-500">{val.raw} · w{val.weight}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div className="h-full rounded-full bg-teal-500" style={{ width: `${val.raw}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function SkillChips({ skills, variant }) {
  if (!skills?.length) return <p className="text-xs text-stone-500">None</p>
  const colors = variant === 'missing'
    ? 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
    : 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
  return (
    <div className="flex flex-wrap gap-1">
      {skills.map((s) => (
        <span key={s} className={`rounded-md px-2 py-0.5 text-xs ${colors}`}>{s}</span>
      ))}
    </div>
  )
}

/** The job's facts, scores, fit, AI tools and contacts. The drawer turns the last two off; the full-details page keeps them, unless the job has no stored row to write to. */
/** Why a score deserves less trust, or why there is none. Shown beside the score; it never changes it. */
export function ConfidenceNote({ job }) {
  const insufficient = isInsufficientData(job)
  const reasons = insufficient ? job.insufficientReasons : job.confidence?.level === 'low' ? job.confidence.reasons : []
  if (!reasons?.length) return null
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/60 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/20 dark:text-amber-200">
      <p className="font-medium">{insufficient ? 'Insufficient data: no Fit Score. Paste more of the ad and score again.' : 'Low confidence in this score'}</p>
      <ul className="ml-4 list-disc">{reasons.map((r) => <li key={r}>{r}</li>)}</ul>
    </div>
  )
}

export default function JobDetailBody({ job, apiAvailable, onJobUpdated, onStatusChange, includeTracker = true, includeAiTools = true, includeContacts = true, includeTailor = true }) {
  const showScores = hasMatchScores([job])
  const limits = (job.reasons || []).filter(isCapReason)
  const positiveReasons = (job.reasons || []).filter((r) => !r.startsWith('Red flag:') && !isCapReason(r) && !isFitReason(r))
  const provider = getJobProvider(job)

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-xs text-stone-500">Location</dt>
          <dd>{job.location || '—'}</dd>
          <AuthorizationBadge job={job} />
        </div>
        <div><dt className="text-xs text-stone-500">Provider</dt><dd>{provider || '—'}</dd></div>
        <div><dt className="text-xs text-stone-500">Remote</dt><dd>{job.isRemote ? 'Yes' : 'No'}</dd></div>
        <div><dt className="text-xs text-stone-500">Status</dt><dd><Badge>{jobStatusLabel(job.status)}</Badge></dd></div>
        {job.salaryMonthlyEur && (
          <div>
            <dt className="text-xs text-stone-500">Pay (as listed)</dt>
            <dd className="flex flex-wrap items-center gap-1">
              {formatMonthlyEur(job.salaryMonthlyEur)}
              {salaryBadges(job).map((b) => <Badge key={b.label} variant={b.variant}>{b.label}</Badge>)}
            </dd>
          </div>
        )}
        {job.firstSeen && (
          <div>
            <dt className="text-xs text-stone-500">Seen</dt>
            <dd className="flex flex-wrap items-center gap-1">
              {formatSeen(job.firstSeen)} – {formatSeen(job.lastSeen)}
              {historyBadges(job).map((b) => <Badge key={b.label} variant={b.variant}>{b.label}</Badge>)}
            </dd>
          </div>
        )}
      </dl>

      {job.jobUrl && (
        <a href={job.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-600">
          Open job posting <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}

      {job.descriptionIncomplete && <p className="text-sm text-amber-800 dark:text-amber-300">The ad's full text was not available when you kept it, so this copy is incomplete.</p>}
      <JobDescription text={job.description} />

      <ManualJobSection job={job} onJobUpdated={onJobUpdated} apiAvailable={apiAvailable} />

      {showScores && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <FitScore score={job.matchScore} label={job.matchLabel} reasons={job.insufficientReasons} size="lg" />
            {scoreRowChips(job).map((c) => <Badge key={c.kind} variant={c.variant}>{c.text}</Badge>)}
            <EngineShadowBadge shadow={job.engineShadow} />
          </div>
          <ConfidenceNote job={job} />
          <ScoreBreakdown breakdown={job.scoreBreakdown} />
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Matched skills</h4>
            <SkillChips skills={job.matchedSkills} />
          </div>
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Missing skills</h4>
            <SkillChips skills={job.missingSkills} variant="missing" />
          </div>
          {limits.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">Limits</h4>
              <ul className="list-inside list-disc text-sm text-amber-800 dark:text-amber-300">
                {limits.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          )}
          <FitJudgementSection fit={job.llmFit} />
          <EngineShadowSection shadow={job.engineShadow} />
          {positiveReasons.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Why this scored well</h4>
              <ul className="list-inside list-disc text-sm text-stone-700 dark:text-stone-300">
                {positiveReasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          )}
          {job.redFlags?.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-600">Red flags</h4>
              <ul className="list-inside list-disc text-sm text-red-700 dark:text-red-400">
                {job.redFlags.map((f) => <li key={f}>{f}</li>)}
              </ul>
            </div>
          )}
          {includeTailor && <JobTailorActions job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} />}
        </>
      )}

      {(showScores || job.keptByUser === true) && includeAiTools && (
        <JobAIToolsPanel job={job} onJobUpdated={onJobUpdated} />
      )}

      {includeContacts && <RelatedContactsPanel job={job} onJobUpdated={onJobUpdated} />}
      {includeTracker && <ApplicationTrackerPanel job={job} onStatusChange={onStatusChange} />}
    </div>
  )
}
