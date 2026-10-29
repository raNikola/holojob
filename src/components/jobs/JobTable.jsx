import { useMemo } from 'react'
import { ExternalLink } from 'lucide-react'
import Badge from '../ui/Badge'
import { JOB_STATUSES } from '../../modules/jobs/jobStorage'
import { getJobProvider } from '../../modules/jobs/jobFilters'
import { hasMatchScores } from '../../modules/jobs/matchScore'
import { authorizationBadge } from '../../modules/jobs/workAuthorization'
import { historyBadges } from '../../modules/jobs/jobHistory'
import { salaryBadges } from '../../modules/jobs/jobSalary'
import { isFollowUpDue } from '../../modules/jobs/followUps'
import { ApplyBadge, PriorityBadge } from './JobScoreBadge'
import FitScore from './FitScore'
import JobTailorActions from './JobTailorActions'
import { EngineShadowBadge } from './EngineShadowSection'
import SortableTh, { useTableSort } from '../ui/SortableTh'
import { sortRows } from '../../modules/tableSort'
import { PRIORITIES } from '../../modules/jobs/matchScore'

const COLUMNS = {
  score: { type: 'number', value: (j) => j.matchScore },
  title: { type: 'text', value: (j) => j.title },
  company: { type: 'text', value: (j) => j.company },
  location: { type: 'text', value: (j) => j.location },
  provider: { type: 'text', value: (j) => getJobProvider(j) },
  priority: { type: 'rank', order: PRIORITIES, value: (j) => j.priority },
  status: { type: 'text', value: (j) => j.status || 'new' },
}
const DEFAULT_SORT = { key: 'score', dir: 'desc' }

const STATUS_VARIANT = {
  new: 'default',
  saved: 'high',
  rejected: 'low',
  applied_manually: 'medium',
}

function StatusBadge({ status }) {
  const label = status?.replace(/_/g, ' ') || 'new'
  return <Badge variant={STATUS_VARIANT[status] || 'default'}>{label}</Badge>
}

function FollowUpBadge({ job }) {
  if (!isFollowUpDue(job.applicationTracking)) return null
  return <Badge variant="medium">Follow-Up Required</Badge>
}

function HistoryBadges({ job }) {
  const badges = [...historyBadges(job), ...salaryBadges(job)]
  if (!badges.length) return null
  return (
    <>
      {badges.map((b) => (
        <span key={b.label} title={b.reason}><Badge variant={b.variant}>{b.label}</Badge></span>
      ))}
    </>
  )
}

function AuthorizationBadge({ job }) {
  const badge = authorizationBadge(job)
  if (!badge) return null
  return <span title={badge.reason}><Badge variant={badge.variant}>{badge.label}</Badge></span>
}

const PROVIDER_VARIANT = {
  jobspy: 'medium',
  greenhouse: 'high',
  lever: 'high',
  ashby: 'medium',
  wellfound: 'low',
}

function ProviderBadge({ job }) {
  const provider = getJobProvider(job)
  if (!provider) return <span>—</span>
  return <Badge variant={PROVIDER_VARIANT[provider] || 'default'}>{provider}</Badge>
}

function JobActions({ job, onStatusChange }) {
  const others = JOB_STATUSES.filter((s) => s !== job.status)
  return (
    <div className="flex flex-wrap gap-1" onClick={(e) => e.stopPropagation()}>
      {others.map((status) => (
        <button
          key={status}
          type="button"
          onClick={() => onStatusChange(job.jobId, status)}
          className="rounded-md px-2 py-1 text-xs text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"
        >
          {status === 'applied_manually' ? 'Applied' : status.charAt(0).toUpperCase() + status.slice(1)}
        </button>
      ))}
    </div>
  )
}

function JobCard({
  job,
  onStatusChange,
  apiAvailable,
  onJobUpdated,
  showScores,
  selected,
  onToggleSelect,
  onJobSelect,
}) {
  return (
    <div
      className="cursor-pointer rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900"
      onClick={() => onJobSelect?.(job)}
    >
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect?.(job.jobId)}
          onClick={(e) => e.stopPropagation()}
          className="mt-1 rounded border-stone-300 text-teal-600"
        />
        <div className="flex flex-1 items-start justify-between gap-2">
          <div>
            <h3 className="font-medium text-stone-900 dark:text-stone-100">{job.title}</h3>
            <p className="text-sm text-stone-600 dark:text-stone-400">{job.company}</p>
          </div>
          <div className="flex flex-col items-end gap-1">
            {showScores && <FitScore score={job.matchScore} label={job.matchLabel} />}
            {showScores && <EngineShadowBadge shadow={job.engineShadow} />}
            {showScores && <AuthorizationBadge job={job} />}
            <StatusBadge status={job.status} />
            <HistoryBadges job={job} />
            <FollowUpBadge job={job} />
          </div>
        </div>
      </div>
      {showScores && (job.priority || job.applyRecommendation) && (
        <div className="mt-2 flex flex-wrap gap-1">
          <PriorityBadge priority={job.priority} />
          <ApplyBadge recommendation={job.applyRecommendation} />
        </div>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-stone-600 dark:text-stone-400">
        <div><dt className="font-medium text-stone-500">Location</dt><dd>{job.location || '—'}</dd></div>
        <div><dt className="font-medium text-stone-500">Provider</dt><dd><ProviderBadge job={job} /></dd></div>
      </dl>
      <div className="mt-3 flex items-start justify-between gap-2" onClick={(e) => e.stopPropagation()}>
        {job.jobUrl ? (
          <a href={job.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-600">
            Open link <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : <span />}
        <JobActions job={job} onStatusChange={onStatusChange} />
      </div>
      {showScores && (
        <div className="mt-3 border-t border-stone-100 pt-3 dark:border-stone-800" onClick={(e) => e.stopPropagation()}>
          <JobTailorActions job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} />
        </div>
      )}
    </div>
  )
}

export default function JobTable({
  jobs: unsortedJobs,
  onStatusChange,
  apiAvailable,
  onJobUpdated,
  selectedJobIds = [],
  onToggleSelect,
  onToggleSelectAll,
  onJobSelect,
}) {
  const [sort, onSort] = useTableSort(DEFAULT_SORT, COLUMNS)
  const jobs = useMemo(() => sortRows(unsortedJobs, sort, COLUMNS), [unsortedJobs, sort])
  const showScores = hasMatchScores(jobs)
  const showProvider = jobs.some((j) => getJobProvider(j))
  const allSelected = jobs.length > 0 && jobs.every((j) => selectedJobIds.includes(j.jobId))

  if (!jobs.length) {
    return (
      <p className="rounded-xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm text-stone-500 dark:border-stone-700">
        No jobs match the current filters.
      </p>
    )
  }

  return (
    <>
      <div className="hidden overflow-x-auto rounded-xl border border-stone-200 dark:border-stone-800 md:block">
        <table className="w-full min-w-[1150px] text-left text-sm">
          <thead className="border-b border-stone-200 bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:border-stone-800 dark:bg-stone-900">
            <tr>
              <th className="px-4 py-3">
                <input type="checkbox" checked={allSelected} onChange={onToggleSelectAll} className="rounded border-stone-300 text-teal-600" />
              </th>
              {showScores && <SortableTh label="Score" sortKey="score" sort={sort} onSort={onSort} className="px-4 py-3" />}
              <SortableTh label="Title" sortKey="title" sort={sort} onSort={onSort} className="px-4 py-3" />
              <SortableTh label="Company" sortKey="company" sort={sort} onSort={onSort} className="px-4 py-3" />
              <SortableTh label="Location" sortKey="location" sort={sort} onSort={onSort} className="px-4 py-3" />
              {showProvider && <SortableTh label="Provider" sortKey="provider" sort={sort} onSort={onSort} className="px-4 py-3" />}
              {showScores && <SortableTh label="Priority" sortKey="priority" sort={sort} onSort={onSort} className="px-4 py-3" />}
              <SortableTh label="Status" sortKey="status" sort={sort} onSort={onSort} className="px-4 py-3" />
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
            {jobs.map((job) => (
              <tr
                key={job.jobId}
                className="cursor-pointer bg-white hover:bg-stone-50 dark:bg-stone-950 dark:hover:bg-stone-900"
                onClick={() => onJobSelect?.(job)}
              >
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedJobIds.includes(job.jobId)}
                    onChange={() => onToggleSelect?.(job.jobId)}
                    className="rounded border-stone-300 text-teal-600"
                  />
                </td>
                {showScores && (
                  <td className="px-4 py-3">
                    <FitScore score={job.matchScore} label={job.matchLabel} />
                    {job.engineShadow && <div className="mt-1"><EngineShadowBadge shadow={job.engineShadow} /></div>}
                    <div className="mt-1"><AuthorizationBadge job={job} /></div>
                  </td>
                )}
                <td className="px-4 py-3 font-medium text-stone-900 dark:text-stone-100">
                  <div>{job.title}</div>
                  <div className="mt-1 flex flex-wrap gap-1"><HistoryBadges job={job} /><FollowUpBadge job={job} /></div>
                </td>
                <td className="px-4 py-3 text-stone-600 dark:text-stone-400">{job.company}</td>
                <td className="px-4 py-3 text-stone-600 dark:text-stone-400">{job.location || '—'}</td>
                {showProvider && <td className="px-4 py-3"><ProviderBadge job={job} /></td>}
                {showScores && <td className="px-4 py-3"><PriorityBadge priority={job.priority} /></td>}
                <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <JobActions job={job} onStatusChange={onStatusChange} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-3 md:hidden">
        {jobs.map((job) => (
          <JobCard
            key={job.jobId}
            job={job}
            onStatusChange={onStatusChange}
            apiAvailable={apiAvailable}
            onJobUpdated={onJobUpdated}
            showScores={showScores}
            selected={selectedJobIds.includes(job.jobId)}
            onToggleSelect={onToggleSelect}
            onJobSelect={onJobSelect}
          />
        ))}
      </div>
    </>
  )
}
