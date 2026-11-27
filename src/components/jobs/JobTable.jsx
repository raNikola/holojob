import { Fragment, useMemo, useRef, useState } from 'react'
import { Bookmark, CircleDot, ExternalLink, SquareCheckBig, X } from 'lucide-react'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import { useMediaQuery } from '../../hooks/useMediaQuery'
import { DEFAULT_SORT, SORT_COLUMNS, everySelected, orderRows } from '../../modules/jobs/jobTableModel'
import { SERVER_ONLY_NOTE, classBadges, rowKind, selectableIds } from '../../modules/jobs/jobListView'
import KeepAdButton from './KeepAdButton'
import { JOB_STATUSES } from '../../modules/jobs/jobStorage'
import { getJobProvider } from '../../modules/jobs/jobFilters'
import { hasMatchScores } from '../../modules/jobs/matchScore'
import { groupHeading } from '../../modules/jobs/fitTier'
import { displayLocation } from '../../modules/jobs/locationDisplay'
import { historyBadges } from '../../modules/jobs/jobHistory'
import { repostBadge } from '../../modules/jobs/adDerived'
import { APPROXIMATE_SALARY_NOTE, approximateMonthlyEur, salaryBadges, statedSalary } from '../../modules/jobs/jobSalary'
import { isFollowUpDue } from '../../modules/jobs/followUps'
import FitTier from './FitTier'
import AuthorizationBadge from './AuthorizationBadge'
import RoleClassBadge from './RoleClassBadge'
import JobTailorActions from './JobTailorActions'
import SortableTh, { useTableSort } from '../ui/SortableTh'
import { dayOf, deadlineStatus } from '../../modules/jobs/jobDeadline'
import { jobStatusLabel } from '../../modules/jobs/manualJob'

const NO_SELECTION = new Set()
const DESKTOP = '(min-width: 768px)' // Tailwind's md, the width the two layouts always switched at

const STATUS_VARIANT = {
  new: 'default',
  saved: 'high',
  rejected: 'low',
  applied_manually: 'medium',
}

/** A history-only row nobody reviewed says so in other words: "Unreviewed" would claim a triage the owner never saw. */
export const HISTORY_ONLY_LABEL = 'History only'
export const HISTORY_ONLY_NOTE = 'Known from the job history. Press Keep this ad to review it.'

function StatusBadge({ status, historyOnly = false }) {
  if (historyOnly && (!status || status === 'new')) {
    return <span title={HISTORY_ONLY_NOTE}><Badge variant="default">{HISTORY_ONLY_LABEL}</Badge></span>
  }
  return <Badge variant={STATUS_VARIANT[status] || 'default'}>{jobStatusLabel(status)}</Badge>
}

function FollowUpBadge({ job }) {
  if (!isFollowUpDue(job.applicationTracking)) return null
  return <Badge variant="medium">Follow-Up Required</Badge>
}

function HistoryBadges({ job, classView }) {
  const badges = [...(classView ? classBadges(job) : historyBadges(job)), ...salaryBadges(job), ...[repostBadge(job)].filter(Boolean)]
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

const NOT_SPECIFIED = <span className="text-stone-400 dark:text-stone-500">Not specified</span>

function SalaryText({ job }) {
  const stated = statedSalary(job.salary)
  if (!stated) return NOT_SPECIFIED
  const approximate = approximateMonthlyEur(job)
  return (
    <>
      <span className="line-clamp-2" title={stated}>{stated}</span>
      {approximate && <span className="block text-xs text-stone-500 dark:text-stone-500" title={APPROXIMATE_SALARY_NOTE}>{approximate}</span>}
    </>
  )
}

function ApplyBy({ job, today }) {
  const status = deadlineStatus(job, today)
  if (status.key === 'unknown') return NOT_SPECIFIED
  if (!status.variant) return <span title={status.note}>{status.label}</span>
  return <span title={status.note}><Badge variant={status.variant}>{status.label}</Badge></span>
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

// `triage`: a status on a row only the server holds is written to the server's job state, so it is allowed (the server list is on). Without it such a row is read-only until Keep.
function JobActions({ job, onStatusChange, onApply, triage = false }) {
  const serverRow = rowKind(job) === 'server' && !triage
  const others = JOB_STATUSES.filter((s) => s !== job.status)
  return (
    <div className="flex gap-0.5" onClick={(e) => e.stopPropagation()}>
      {others.map((status) => {
        const { Icon, label } = ACTION_ICON[status]
        // Applied is never a stored status: the button opens the quick form, and the status shows once the server has saved the application.
        const isApply = status === 'applied_manually'
        const readOnly = serverRow && !isApply
        return (
          <button
            key={status}
            type="button"
            title={readOnly ? SERVER_ONLY_NOTE : label}
            aria-label={readOnly ? `${label}: ${SERVER_ONLY_NOTE}` : label}
            disabled={readOnly}
            onClick={() => (isApply ? onApply?.(job) : onStatusChange(job.jobId, status))}
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
  onApply,
  apiAvailable,
  onJobUpdated,
  showScores,
  triage = false,
  selected,
  onToggleSelect,
  onJobSelect,
  classView,
  onAddFromRow,
  today,
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
            disabled={kind === 'server' && !triage}
            title={kind === 'server' && !triage ? SERVER_ONLY_NOTE : undefined}
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
            {showScores && <FitTier job={job} />}
            {showScores && <RoleClassBadge job={job} />}
            <StatusBadge status={job.status} historyOnly={rowKind(job) === 'server' && !triage} />
            <HistoryBadges job={job} classView={classView} />
            <FollowUpBadge job={job} />
          </div>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-stone-600 dark:text-stone-400">
        <div><dt className="font-medium text-stone-500">Location</dt><dd><LocationText job={job} /><AuthorizationBadge job={job} /></dd></div>
        <div><dt className="font-medium text-stone-500">Provider</dt><dd><ProviderBadge job={job} /></dd></div>
        <div><dt className="font-medium text-stone-500">Salary</dt><dd><SalaryText job={job} /></dd></div>
        <div><dt className="font-medium text-stone-500">Apply by</dt><dd><ApplyBy job={job} today={today} /></dd></div>
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
              <JobActions job={job} onStatusChange={onStatusChange} onApply={onApply} triage={triage} />
              {kind === 'server' && <KeepAdButton row={job} />}
            </div>
          </>
        )}
      </div>
      {showScores && kind === 'stored' && (
        <div className="mt-3 border-t border-stone-100 pt-3 dark:border-stone-800" onClick={(e) => e.stopPropagation()}>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">AI Tools</h4>
          <JobTailorActions job={job} apiAvailable={apiAvailable} onJobUpdated={onJobUpdated} />
        </div>
      )}
    </div>
  )
}

export default function JobTable({
  jobs: unsortedJobs,
  onStatusChange,
  onApply,
  apiAvailable,
  onJobUpdated,
  selectedJobIds = NO_SELECTION,
  onToggleSelect,
  onToggleSelectAll,
  onJobSelect,
  classView = false,
  onAddFromRow,
  reference,
  server = null,
}) {
  // `server` is the list as the server pages it (src/modules/jobs/serverList.js): the rows arrive in the server's order, the sort and Show more are asked of the
  // server, and the table sorts, cuts and counts nothing itself. Without it (demo data, no API) the table works from the whole list it is given, as ever.
  // server = { total, pageSize, loadingMore, sort, onSort, onShowMore, hasScores, hasProvider }
  const [ownSort, ownOnSort] = useTableSort(DEFAULT_SORT, SORT_COLUMNS)
  const sort = server ? (server.sort ?? DEFAULT_SORT) : ownSort
  const onSort = server ? server.onSort : ownOnSort
  const triage = Boolean(server) // the server list is on: a status on a row only the server holds goes to the server
  const [openedAt] = useState(() => Date.now())
  const today = dayOf(reference ?? openedAt)
  const pagerRef = useRef(null)
  const isDesktop = useMediaQuery(DESKTOP, true)
  // The whole list is sorted first; only then is a batch taken from it. The list's other uses read the whole list too.
  const jobs = useMemo(() => {
    if (server) return unsortedJobs // already in the server's order
    return orderRows(unsortedJobs, sort, today) // the default sort is told by identity: any click replaces it, even back to the same column
  }, [unsortedJobs, sort, today, server])
  const visibleJobs = jobs // every row it is given: with the server's list the server pages, without it (demo data, no API) the list is small
  const headingAt = (index) => (sort === DEFAULT_SORT ? groupHeading(visibleJobs, index) : null)
  const showScores = server ? server.hasScores : hasMatchScores(jobs)
  const showProvider = server ? server.hasProvider : jobs.some((j) => getJobProvider(j))
  const selectable = useMemo(() => selectableIds(jobs, triage), [jobs, triage])
  const allSelected = useMemo(() => everySelected(selectedJobIds, selectable), [selectedJobIds, selectable])
  const notShown = useMemo(() => {
    const shown = new Set(jobs.map((job) => job.jobId))
    return [...selectedJobIds].filter((id) => !shown.has(id)).length
  }, [selectedJobIds, jobs])
  // With the server's list on, every ad can be selected (a status goes to the server's job state); without it only stored rows can.
  const unsaved = jobs.length - selectable.length
  const total = server ? server.total : jobs.length
  const selectAllLabel = server
    ? `Select all filtered jobs, not only the ${visibleJobs.length} shown`
    : `Select all ${selectable.length} filtered jobs${unsaved ? ' saved in this browser' : ''}, not only the ${visibleJobs.length} shown`

  if (!jobs.length) {
    return (
      <p className="rounded-xl border border-dashed border-stone-300 px-4 py-8 text-center text-sm text-stone-500 dark:border-stone-700">
        {server?.loading ? 'Loading the list…' : 'No jobs match the current filters.'}
      </p>
    )
  }

  const remaining = total - visibleJobs.length // only the server's list has rows it has not sent yet
  const step = server?.pageSize ?? 0
  const handleShowMore = () => {
    server?.onShowMore()
    if (remaining <= step) pagerRef.current?.focus() // the button is about to go: keep the keyboard's place
  }

  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-500 dark:text-stone-400">
        {notShown > 0 && <span>{notShown} selected {notShown === 1 ? 'job is' : 'jobs are'} not shown yet</span>}
      </div>
      {isDesktop ? (
      <div className="overflow-x-auto rounded-xl border border-stone-200 dark:border-stone-800">
        <table className="w-full min-w-[1180px] text-left text-sm">
          <thead className="border-b border-stone-200 bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:border-stone-800 dark:bg-stone-900">
            <tr>
              <th className="px-3 py-2">
                {selectable.length > 0 && <input type="checkbox" checked={allSelected} onChange={onToggleSelectAll} aria-label={selectAllLabel} title={selectAllLabel} className="rounded border-stone-300 text-teal-600" />}
              </th>
              {showScores && <SortableTh label="Fit tier" sortKey="tier" sort={sort} onSort={onSort} className="px-3 py-2" />}
              <SortableTh label="Title" sortKey="title" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Company" sortKey="company" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Location" sortKey="location" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Salary" sortKey="salary" sort={sort} onSort={onSort} className="px-3 py-2" />
              <SortableTh label="Apply by" sortKey="deadline" sort={sort} onSort={onSort} className="whitespace-nowrap px-3 py-2" />
              {showProvider && <SortableTh label="Provider" sortKey="provider" sort={sort} onSort={onSort} className="px-3 py-2" />}
              <SortableTh label="Status" sortKey="status" sort={sort} onSort={onSort} className="px-3 py-2" />
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100 dark:divide-stone-800">
            {visibleJobs.map((job, index) => (
              <Fragment key={job.jobId}>
              {headingAt(index) && (
                <tr className="bg-stone-50 dark:bg-stone-900"><th colSpan={12} className="px-3 py-1.5 text-left text-xs font-medium text-stone-600 dark:text-stone-400">{headingAt(index)}</th></tr>
              )}
              <tr
                className={`${rowKind(job) === 'filtered' ? '' : 'cursor-pointer '}bg-white hover:bg-stone-50 dark:bg-stone-950 dark:hover:bg-stone-900`}
                onClick={rowKind(job) === 'filtered' ? undefined : () => onJobSelect?.(job)}
              >
                <td className="px-3 py-2 align-top" onClick={(e) => e.stopPropagation()}>
                  {rowKind(job) !== 'filtered' && (
                    <input
                      type="checkbox"
                      checked={selectedJobIds.has(job.jobId)}
                      disabled={rowKind(job) === 'server' && !triage}
                      title={rowKind(job) === 'server' && !triage ? SERVER_ONLY_NOTE : undefined}
                      onChange={() => onToggleSelect?.(job.jobId)}
                      className="rounded border-stone-300 text-teal-600"
                    />
                  )}
                </td>
                {showScores && (
                  <td className="px-3 py-2 align-top">
                    <FitTier job={job} />
                  </td>
                )}
                <td className="w-full px-3 py-2 align-top font-medium text-stone-900 dark:text-stone-100">
                  <div>{job.title}</div>
                  <div className="mt-1 flex flex-wrap gap-1">{showScores && <RoleClassBadge job={job} />}<HistoryBadges job={job} classView={classView} /><FollowUpBadge job={job} /></div>
                  <ReasonLine job={job} classView={classView} />
                </td>
                <td className="max-w-[12rem] px-3 py-2 align-top text-stone-600 dark:text-stone-400">{job.company}</td>
                <td className="max-w-[14rem] px-3 py-2 align-top text-stone-600 dark:text-stone-400">
                  <LocationText job={job} />
                  <AuthorizationBadge job={job} />
                </td>
                <td className="max-w-[11rem] px-3 py-2 align-top text-stone-600 dark:text-stone-400"><SalaryText job={job} /></td>
                <td className="whitespace-nowrap px-3 py-2 align-top text-stone-600 dark:text-stone-400"><ApplyBy job={job} today={today} /></td>
                {showProvider && <td className="px-3 py-2 align-top"><ProviderBadge job={job} /></td>}
                <td className="px-3 py-2 align-top"><StatusBadge status={job.status} historyOnly={rowKind(job) === 'server' && !triage} /></td>
                <td className="px-3 py-2 align-top" onClick={(e) => e.stopPropagation()}>
                  {rowKind(job) === 'filtered' ? <FilteredRowActions job={job} onAddFromRow={onAddFromRow} /> : <JobActions job={job} onStatusChange={onStatusChange} onApply={onApply} triage={triage} />}
                  {rowKind(job) === 'server' && <div className="mt-1"><KeepAdButton row={job} /></div>}
                </td>
              </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      ) : (
      <div className="space-y-3">
        {visibleJobs.map((job, index) => (
          <Fragment key={job.jobId}>
          {headingAt(index) && (
            <p className="px-1 text-xs font-medium text-stone-600 dark:text-stone-400">{headingAt(index)}</p>
          )}
          <JobCard
            job={job}
            onStatusChange={onStatusChange}
            onApply={onApply}
            triage={triage}
            apiAvailable={apiAvailable}
            onJobUpdated={onJobUpdated}
            showScores={showScores}
            today={today}
            selected={selectedJobIds.has(job.jobId)}
            onToggleSelect={onToggleSelect}
            onJobSelect={onJobSelect}
            classView={classView}
            onAddFromRow={onAddFromRow}
          />
          </Fragment>
        ))}
      </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span ref={pagerRef} tabIndex={-1} role="status" className="text-sm text-stone-600 focus:outline-none dark:text-stone-400">
          Showing {visibleJobs.length} of {total}
        </span>
        {remaining > 0 && (
          <Button variant="secondary" onClick={handleShowMore} disabled={Boolean(server?.loadingMore)}>
            {server?.loadingMore ? 'Loading…' : `Show ${Math.min(remaining, step)} more`}
          </Button>
        )}
      </div>
    </>
  )
}
