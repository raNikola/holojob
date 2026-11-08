import { useMemo, useRef, useState } from 'react'
import { Bookmark, CircleDot, ExternalLink, SquareCheckBig, X } from 'lucide-react'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { JOB_PAGE_SIZE, everySelected, closedLast, pageLimit, selectedNotShown, showMore } from '../../modules/jobs/jobTableModel'
import { SERVER_ONLY_NOTE, classBadges, rowKind, selectableIds } from '../../modules/jobs/jobListView'
import KeepAdButton from './KeepAdButton'
import { JOB_STATUSES } from '../../modules/jobs/jobStorage'
import { getJobProvider } from '../../modules/jobs/jobFilters'
import { hasMatchScores } from '../../modules/jobs/matchScore'
import { displayLocation } from '../../modules/jobs/locationDisplay'
import { historyBadges } from '../../modules/jobs/jobHistory'
import { salaryBadges } from '../../modules/jobs/jobSalary'
import { isFollowUpDue } from '../../modules/jobs/followUps'
import { ApplyBadge, PriorityBadge } from './JobScoreBadge'
import FitScore from './FitScore'
import AuthorizationBadge from './AuthorizationBadge'
import JobTailorActions from './JobTailorActions'
import { EngineShadowBadge } from './EngineShadowSection'
import SortableTh, { useTableSort } from '../ui/SortableTh'
import { sortRows } from '../../modules/tableSort'
import { PRIORITIES } from '../../modules/jobs/matchScore'
import { jobStatusLabel } from '../../modules/jobs/manualJob'

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
const NO_SELECTION = new Set()
const DESKTOP = '(min-width: 768px)' // Tailwind's md, the width the two layouts always switched at

const STATUS_VARIANT = {
  new: 'default',
  saved: 'high',
  rejected: 'low',
  applied_manually: 'medium',
}

function StatusBadge({ status }) {
  const label = jobStatusLabel(status)
  return <Badge variant={STATUS_VARIANT[status] || 'default'}>{label}</Badge>
}

function FollowUpBadge({ job }) {
  if (!isFollowUpDue(job.applicationTracking)) return null
  return <Badge variant="medium">Follow-Up Required</Badge>
}

function HistoryBadges({ job, classView }) {
  const badges = [...(classView ? classBadges(job) : historyBadges(job)), ...salaryBadges(job)]
  if (!badges.length) return null
  return (
    <>
      {badges.map((b) => (
        <span key={b.label} title={b.reason}><Badge variant={b.variant}>{b.label}</Badge></span>
      ))}
    </>
  )
}

/** The route's words for where this row stands. */
function ReasonLine({ job, classView }) {
  if (!classView || !job.reason || job.class === 'found') return null
  return <p className="mt-1 text-xs font-normal text-stone-500 dark:text-stone-400">{job.reason}</p>
}

/** A filtered row: only what the ad gave, a link to it and the form to add it by hand. */
function FilteredRowActions({ job, onAddFromRow }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <a href={job.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-600">
        Open ad <ExternalLink className="h-3.5 w-3.5" />
      </a>
      <button type="button" onClick={() => onAddFromRow?.(job)} className="rounded-md border border-stone-300 px-2 py-1 text-xs text-stone-700 hover:bg-stone-50 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-800">
        Add job
      </button>
    </div>
  )
}

function LocationText({ job }) {
  if (!job.location) return <span>—</span>
  return <span className="line-clamp-2" title={job.location}>{displayLocation(job.location) || job.location}</span>
}

function ProviderBadge({ job }) {
  const provider = getJobProvider(job)
  if (!provider) return <span>—</span>
  return <span className="rounded bg-stone-50 px-1.5 py-0.5 text-[11px] text-stone-500 dark:bg-stone-900 dark:text-stone-500">{provider}</span>
}

const ACTION_ICON = {
  new: { Icon: CircleDot, label: 'Mark as new' },
  saved: { Icon: Bookmark, label: 'Save' },
  rejected: { Icon: X, label: 'Reject' },
  applied_manually: { Icon: SquareCheckBig, label: 'Mark as applied' },
}

function JobActions({ job, onStatusChange }) {
  const readOnly = rowKind(job) === 'server'
  const others = JOB_STATUSES.filter((s) => s !== job.status)
  return (
    <div className="flex gap-0.5" onClick={(e) => e.stopPropagation()}>
      {others.map((status) => {
        const { Icon, label } = ACTION_ICON[status]
        return (
          <button
            key={status}
            type="button"
            title={readOnly ? SERVER_ONLY_NOTE : label}
            aria-label={readOnly ? `${label}: ${SERVER_ONLY_NOTE}` : label}
            disabled={readOnly}
            onClick={() => onStatusChange(job.jobId, status)}
            className="rounded-md p-1.5 text-stone-500 hover:bg-stone-100 hover:text-stone-800 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
          </button>
        )
      })}
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
  classView,
  onAddFromRow,
}) {
  const kind = rowKind(job)
  return (
    <div
      className={`${kind === 'filtered' ? '' : 'cursor-pointer '}rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900`}
      onClick={kind === 'filtered' ? undefined : () => onJobSelect?.(job)}
    >
      <div className="flex items-start gap-2">
        {kind !== 'filtered' && (
          <input
            type="checkbox"
            checked={selected}
            disabled={kind === 'server'}
            title={kind === 'server' ? SERVER_ONLY_NOTE : undefined}
            onChange={() => onToggleSelect?.(job.jobId)}
            onClick={(e) => e.stopPropagation()}
            className="mt-1 rounded border-stone-300 text-teal-600"
          />
        )}
        <div className="flex flex-1 items-start justify-between gap-2">
          <div>
            <h3 className="font-medium text-stone-900 dark:text-stone-100">{job.title}</h3>
            <p className="text-sm text-stone-600 dark:text-stone-400">{job.company}</p>
            <ReasonLine job={job} classView={classView} />
          </div>
          <div className="flex flex-col items-end gap-1">
            {showScores && <FitScore score={job.matchScore} label={job.matchLabel} emptyLabel="Not scored" />}
            {showScores && <EngineShadowBadge shadow={job.engineShadow} />}
            <StatusBadge status={job.status} />
            <HistoryBadges job={job} classView={classView} />
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
        <div><dt className="font-medium text-stone-500">Location</dt><dd><LocationText job={job} /><AuthorizationBadge job={job} /></dd></div>
        <div><dt className="font-medium text-stone-500">Provider</dt><dd><ProviderBadge job={job} /></dd></div>
      </dl>
      <div className="mt-3 flex items-start justify-between gap-2" onClick={(e) => e.stopPropagation()}>
        {kind === 'filtered' ? <FilteredRowActions job={job} onAddFromRow={onAddFromRow} /> : (
          <>
            {job.jobUrl ? (
              <a href={job.jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-teal-600">
                Open link <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : <span />}
            <div className="flex flex-col items-end gap-1">
              <JobActions job={job} onStatusChange={onStatusChange} />
              {kind === 'server' && <KeepAdButton row={job} />}
            </div>
          </>
        )}
      </div>
      {showScores && kind === 'stored' && (
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
  selectedJobIds = NO_SELECTION,
  onToggleSelect,
  onToggleSelectAll,
  onJobSelect,
  filterKey = '',
  classView = false,
  onAddFromRow,
}) {
  const [sort, onSort] = useTableSort(DEFAULT_SORT, COLUMNS)
  const [paging, setPaging] = useState(null)
  const pagerRef = useRef(null)
  const isDesktop = useMediaQuery(DESKTOP, true)
  // The whole list is sorted first; only then is a batch taken from it. The list's other uses read the whole list too.
  const jobs = useMemo(() => {
    const sorted = sortRows(unsortedJobs, sort, COLUMNS)
    return sort === DEFAULT_SORT ? closedLast(sorted) : sorted // DEFAULT_SORT by identity: any click replaces it, even back to the same column
  }, [unsortedJobs, sort])
  const pageKey = `${filterKey}|${sort.key}|${sort.dir}`
  const limit = pageLimit(paging, pageKey)
  const visibleJobs = useMemo(() => jobs.slice(0, limit), [jobs, limit])
  const showScores = hasMatchScores(jobs)
  const showProvider = jobs.some((j) => getJobProvider(j))
  const selectable = useMemo(() => selectableIds(jobs), [jobs])
  const allSelected = useMemo(() => everySelected(selectedJobIds, selectable), [selectedJobIds, selectable])
  const notShown = useMemo(() => selectedNotShown(selectedJobIds, jobs, limit), [selectedJobIds, jobs, limit])
  // Only stored rows can be selected: bulk actions act on those.
  const unsaved = jobs.length - selectable.length
  const selectAllLabel = `Select all ${selectable.length} filtered jobs${unsaved ? ' saved in this browser' : ''}, not only the ${visibleJobs.length} shown`

  if (!jobs.length) {
    return (
      <p className="rounded-xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm text-stone-500 dark:border-stone-700">
        No jobs match the current filters.
      </p>
    )
  }

  const remaining = jobs.length - visibleJobs.length
  const handleShowMore = () => {
    setPaging(showMore(paging, pageKey))
    if (remaining <= JOB_PAGE_SIZE) pagerRef.current?.focus() // the button is about to go: keep the keyboard's place
  }

  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
        {selectable.length > 0 && (
          <button type="button" className="underline hover:text-stone-800 dark:hover:text-stone-100" onClick={onToggleSelectAll}>
            {allSelected ? `Clear selection of all ${selectable.length} filtered jobs` : `Select all ${selectable.length} filtered jobs`}{unsaved ? ' saved in this browser' : ''}
          </button>
        )}
        {notShown > 0 && <span>{notShown} selected {notShown === 1 ? 'job is' : 'jobs are'} not shown yet</span>}
      </div>
      {isDesktop ? (
      <div className="overflow-x-auto rounded-xl border border-stone-200 dark:border-stone-800">
        <table className="w-full min-w-[960px] text-left text-sm">
          <thead className="border-b border-stone-200 bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:border-stone-800 dark:bg-stone-900">
            <tr>
              <th className="px-3 py-2">
                {selectable.length > 0 && <input type="checkbox" checked={allSelected} onChange={onToggleSelectAll} aria-label={selectAllLabel} title={selectAllLabel} className="rounded border-stone-300 text-teal-600" />}
              </th>
              {showScores && <SortableTh label="Score" sortKey="score" sort={sort} onSort={onSort} className="px-3 py-2" />}
              <SortableTh label="Title" sortKey="title" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Company" sortKey="company" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Location" sortKey="location" sort={sort} onSort={onSort} className="px-3 py-2" />
              {showProvider && <SortableTh label="Provider" sortKey="provider" sort={sort} onSort={onSort} className="px-3 py-2" />}
              {showScores && <SortableTh label="Priority" sortKey="priority" sort={sort} onSort={onSort} className="px-3 py-2" />}
              <SortableTh label="Status" sortKey="status" sort={sort} onSort={onSort} className="px-3 py-2" />
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
            {visibleJobs.map((job) => (
              <tr
                key={job.jobId}
                className={`${rowKind(job) === 'filtered' ? '' : 'cursor-pointer '}bg-white hover:bg-stone-50 dark:bg-stone-950 dark:hover:bg-stone-900`}
                onClick={rowKind(job) === 'filtered' ? undefined : () => onJobSelect?.(job)}
              >
                <td className="px-3 py-2 align-top" onClick={(e) => e.stopPropagation()}>
                  {rowKind(job) !== 'filtered' && (
                    <input
                      type="checkbox"
                      checked={selectedJobIds.has(job.jobId)}
                      disabled={rowKind(job) === 'server'}
                      title={rowKind(job) === 'server' ? SERVER_ONLY_NOTE : undefined}
                      onChange={() => onToggleSelect?.(job.jobId)}
                      className="rounded border-stone-300 text-teal-600"
                    />
                  )}
                </td>
                {showScores && (
                  <td className="px-3 py-2 align-top">
                    <FitScore score={job.matchScore} label={job.matchLabel} emptyLabel="Not scored" />
                    {job.engineShadow && <div className="mt-1"><EngineShadowBadge shadow={job.engineShadow} /></div>}
                  </td>
                )}
                <td className="w-full px-3 py-2 align-top font-medium text-stone-900 dark:text-stone-100">
                  <div>{job.title}</div>
                  <div className="mt-1 flex flex-wrap gap-1"><HistoryBadges job={job} classView={classView} /><FollowUpBadge job={job} /></div>
                  <ReasonLine job={job} classView={classView} />
                </td>
                <td className="max-w-[12rem] px-3 py-2 align-top text-stone-600 dark:text-stone-400">{job.company}</td>
                <td className="max-w-[14rem] px-3 py-2 align-top text-stone-600 dark:text-stone-400">
                  <LocationText job={job} />
                  <AuthorizationBadge job={job} />
                </td>
                {showProvider && <td className="px-3 py-2 align-top"><ProviderBadge job={job} /></td>}
                {showScores && <td className="px-3 py-2 align-top"><PriorityBadge priority={job.priority} /></td>}
                <td className="px-3 py-2 align-top"><StatusBadge status={job.status} /></td>
                <td className="px-3 py-2 align-top" onClick={(e) => e.stopPropagation()}>
                  {rowKind(job) === 'filtered' ? <FilteredRowActions job={job} onAddFromRow={onAddFromRow} /> : <JobActions job={job} onStatusChange={onStatusChange} />}
                  {rowKind(job) === 'server' && <div className="mt-1"><KeepAdButton row={job} /></div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      ) : (
      <div className="space-y-3">
        {visibleJobs.map((job) => (
          <JobCard
            key={job.jobId}
            job={job}
            onStatusChange={onStatusChange}
            apiAvailable={apiAvailable}
            onJobUpdated={onJobUpdated}
            showScores={showScores}
            selected={selectedJobIds.has(job.jobId)}
            onToggleSelect={onToggleSelect}
            onJobSelect={onJobSelect}
            classView={classView}
            onAddFromRow={onAddFromRow}
          />
        ))}
      </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span ref={pagerRef} tabIndex={-1} role="status" className="text-sm text-stone-600 focus:outline-none dark:text-stone-400">
          Showing {visibleJobs.length} of {jobs.length}
        </span>
        {remaining > 0 && (
          <Button variant="secondary" onClick={handleShowMore}>
            Show {Math.min(remaining, JOB_PAGE_SIZE)} more
          </Button>
        )}
      </div>
    </>
  )
}
