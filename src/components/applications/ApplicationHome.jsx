import { useCallback, useEffect, useMemo, useState } from 'react'
import StatCard from '../ui/StatCard'
import Card from '../ui/Card'
import Tabs from '../ui/Tabs'
import SelectField from '../ui/SelectField'
import ApplicationBoard from './ApplicationBoard'
import ApplicationStatistics from './ApplicationStatistics'
import JobDetailDrawer from '../jobs/JobDetailDrawer'
import { useJobsSync } from '../../hooks/useJobs'
import ApplicationAIInsights from '../ai/ApplicationAIInsights'
import { computeJobStats } from '../../modules/jobs/jobStats'
import {
  loadJobs,
  saveJobs,
} from '../../modules/jobs/jobStorage'
import { normalizeApplicationTracking } from '../../modules/jobs/applicationTracking'
import { applicationOnlyJobs, overlayTracking, trackerStats } from '../../modules/applications/trackingView'
import { columnByJobId, stageFilterOptions } from '../../modules/applications/applicationStatistics'
import { applicationOpenTarget, openJobPage } from '../../modules/jobs/jobRoute'
import { useApplications } from '../../hooks/useApplications'
import { probePipelineApi } from '../../modules/jobs/pipelineRunner'
import { isFollowUpDue } from '../../modules/jobs/followUps'
import { isOutreachFollowUpDue } from '../../modules/outreach/followUpEngine'
import { computeOutreachMetrics } from '../../modules/outreach/outreachMetrics'
import SortableTh, { useTableSort } from '../ui/SortableTh'
import Badge from '../ui/Badge'
import { closedAdIds, AD_CLOSED_NOTE } from '../../modules/jobs/jobHistory'
import { useAllAds } from '../../modules/jobs/useAllAds'
import { sortRows } from '../../modules/tableSort'

const stageOf = (job) => {
  const t = normalizeApplicationTracking(job)
  return t.interviewStage || (t.applied ? 'Applied' : '')
}
const TRACKER_COLUMNS = {
  company: { type: 'text', value: (j) => j.company },
  role: { type: 'text', value: (j) => j.title },
  stage: { type: 'text', value: stageOf },
  applied: { type: 'date', value: (j) => j.applicationTracking?.appliedDate },
  followUp: { type: 'date', value: (j) => normalizeApplicationTracking(j).followUpDate },
  recruiter: { type: 'text', value: (j) => normalizeApplicationTracking(j).recruiterName },
  notes: { type: 'text', value: (j) => normalizeApplicationTracking(j).notes },
}
const APPLICATION_TABS = [
  { id: 'board', label: 'Board' },
  { id: 'statistics', label: 'Statistics' },
]
const TRACKER_DEFAULT_SORT = { key: 'applied', dir: 'desc' }

function hasTrackingData(job) {
  const t = normalizeApplicationTracking(job)
  return t.applied || t.interviewStage || t.notes || t.recruiterName || t.followUpDate
}

function formatDate(value) {
  if (!value) return '—'
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

export default function ApplicationHome() {
  const [state, setState] = useState(() => loadJobs())
  const [selectedJob, setSelectedJob] = useState(null)
  const [pipelineApiAvailable, setPipelineApiAvailable] = useState(false)
  const [tab, setTab] = useState('board')
  const [stageFilter, setStageFilter] = useState('')

  useEffect(() => {
    setState(loadJobs())
    probePipelineApi().then((probe) => setPipelineApiAvailable(probe.available))
  }, [])

  useEffect(() => {
    saveJobs(state)
  }, [state])
  useJobsSync(setState)

  const applications = useApplications()
  const allAds = useAllAds({ enabled: pipelineApiAvailable })
  const adClosed = useMemo(() => closedAdIds(allAds.rows ?? state.jobs), [allAds.rows, state.jobs])
  // Tracking comes from the application store; `state.jobs` stays as saved and is what gets persisted.
  const viewJobs = useMemo(
    () => overlayTracking(state.jobs, applications.status === 'ready' ? applications.store : null, applications.settings),
    [state.jobs, applications.status, applications.store, applications.settings],
  )

  const stats = useMemo(
    // The tracker cards count applications from the store, whether or not their ad still has a row.
    () => ({ ...computeJobStats(viewJobs), ...trackerStats(applications.status === 'ready' ? applications.store : null, applications.settings) }),
    [viewJobs, applications.status, applications.store, applications.settings],
  )
  const outreachMetrics = useMemo(() => computeOutreachMetrics(viewJobs), [viewJobs])

  const [trackerSort, onTrackerSort] = useTableSort(TRACKER_DEFAULT_SORT, TRACKER_COLUMNS)
  const storeReady = applications.status === 'ready'
  const stageOptions = useMemo(
    () => (storeReady ? stageFilterOptions(applications.store, applications.settings) : []),
    [storeReady, applications.store, applications.settings],
  )
  const columns = useMemo(
    () => (storeReady ? columnByJobId(applications.store, applications.settings) : new Map()),
    [storeReady, applications.store, applications.settings],
  )
  // a filter whose stage no longer holds an application is ignored, not left hiding every row
  const activeStageFilter = stageOptions.some((o) => o.value === stageFilter) ? stageFilter : ''
  const trackedJobs = useMemo(() => {
    // An application whose ad has no row is still a row here; it is derived on every render and never saved.
    const applicationRows = storeReady ? applicationOnlyJobs(state.jobs, applications.store, applications.settings) : []
    const rows = [...viewJobs.filter(hasTrackingData), ...applicationRows].filter((job) => !activeStageFilter || columns.get(job.jobId) === activeStageFilter)
    return sortRows(rows, trackerSort, TRACKER_COLUMNS)
  }, [viewJobs, state.jobs, storeReady, applications.store, applications.settings, trackerSort, activeStageFilter, columns])

  // The quick view on the browser row, else Job Details by id. False only for an application saved with no job id.
  const openJob = useCallback((jobId) => {
    const target = applicationOpenTarget(state.jobs, jobId)
    if (target.kind === 'drawer') setSelectedJob(target.job)
    if (target.kind === 'page') openJobPage(target.jobId)
    return target.kind !== 'none'
  }, [state.jobs])

  return (
    <div className="space-y-6">
      <ApplicationAIInsights />

      <Tabs tabs={APPLICATION_TABS} active={tab} onChange={setTab} />

      {tab === 'board' && <ApplicationBoard onOpenJob={openJob} adClosed={adClosed} />}

      {tab === 'statistics' && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label="Applied" value={stats.crmApplied} />
            <StatCard label="Interviewing" value={stats.crmInterviewing} />
            <StatCard
              label="Follow-ups due"
              value={stats.crmFollowUpsDue + outreachMetrics.followUpsDue}
              subtext={outreachMetrics.followUpsDue > 0 ? `${outreachMetrics.followUpsDue} outreach` : undefined}
            />
            <StatCard label="Offers" value={stats.crmOffers} />
            <StatCard label="Rejected" value={stats.crmRejected} />
          </div>

          {storeReady && <ApplicationStatistics store={applications.store} settings={applications.settings} />}
          {!storeReady && applications.status === 'error' && (
            <p className="text-sm text-red-700 dark:text-red-300">Statistics from the tracker are unavailable: {applications.error}</p>
          )}

          <Card title="Application tracker">
            {stageOptions.length > 0 && (
              <div className="mb-3 max-w-xs">
                <SelectField label="Stage" value={activeStageFilter} onChange={setStageFilter} options={stageOptions} placeholder="All stages" />
                {activeStageFilter && <p className="mt-1 text-xs text-stone-500">Jobs still tracked in the old format are not in any stage until the migration runs.</p>}
              </div>
            )}
            {trackedJobs.length === 0 ? (
              <p className="text-sm text-stone-600 dark:text-stone-400">
                No tracked applications yet. Open a job from the Jobs screen and add application details.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-stone-200 text-xs uppercase tracking-wide text-stone-500 dark:border-stone-700">
                      <SortableTh label="Company" sortKey="company" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Role" sortKey="role" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Stage" sortKey="stage" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Applied" sortKey="applied" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Follow-up" sortKey="followUp" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Recruiter" sortKey="recruiter" sort={trackerSort} onSort={onTrackerSort} className="pb-3 pr-4 font-medium" />
                      <SortableTh label="Notes" sortKey="notes" sort={trackerSort} onSort={onTrackerSort} className="pb-3 font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {trackedJobs.map((job) => {
                      const t = normalizeApplicationTracking(job)
                      const crmFollowUpDue = isFollowUpDue(t)
                      const outreachFollowUpDue = isOutreachFollowUpDue(job)
                      return (
                        <tr
                          key={job.jobId ?? job.applicationId}
                          className="cursor-pointer border-b border-stone-100 hover:bg-stone-50 dark:border-stone-800 dark:hover:bg-stone-900/50"
                          onClick={() => openJob(job.jobId)}
                        >
                          <td className="py-3 pr-4 font-medium text-stone-900 dark:text-stone-100">
                            {job.company || '—'}
                            {(crmFollowUpDue || outreachFollowUpDue) && (
                              <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                                Follow-up due
                              </span>
                            )}
                          </td>
                          <td className="py-3 pr-4 text-stone-700 dark:text-stone-300">{job.title || '—'}{adClosed.has(job.jobId) && <span className="ml-2"><span title={AD_CLOSED_NOTE}><Badge variant="low">Ad closed</Badge></span></span>}</td>
                          <td className="py-3 pr-4">{t.interviewStage || (t.applied ? 'Applied' : '—')}</td>
                          <td className="py-3 pr-4">{formatDate(t.appliedDate)}</td>
                          <td className="py-3 pr-4">
                            {formatDate(t.followUpDate)}
                            {outreachFollowUpDue && !t.followUpDate && (
                              <span className="ml-1 text-xs text-amber-600">outreach</span>
                            )}
                          </td>
                          <td className="py-3 pr-4">{t.recruiterName || '—'}</td>
                          <td className="max-w-[200px] truncate py-3 text-stone-600 dark:text-stone-400">{t.notes || '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>


        </>
      )}

      <JobDetailDrawer
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        apiAvailable={pipelineApiAvailable}
      />
    </div>
  )
}
