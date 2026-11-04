import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Loader2, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import Button from '../ui/Button'
import Tabs from '../ui/Tabs'
import JobDiscoverySummary from './JobDiscoverySummary'
import PipelineHealthPanel from './PipelineHealthPanel'
import PipelineOrchestrator from './PipelineOrchestrator'
import JobImportPanel from './JobImportPanel'
import JobUrlImport from './JobUrlImport'
import { migrateLegacyDiscoveryOptions } from '../../modules/sources/sourcesClient'
import AddJobDialog from './AddJobDialog'
import { openJobPage } from '../../modules/jobs/jobRoute'
import { scoreStoredJob } from '../../modules/jobs/manualScoring'
import ApplicationDashboard from './ApplicationDashboard'
import JobFilters from './JobFilters'
import BulkActionsBar from './BulkActionsBar'
import JobTable from './JobTable'
import JobListControls from './JobListControls'
import { useDemoBootstrapContext } from '../demo/DemoBootstrapGate'
import { composeJobList, stripDisplayFields } from '../../modules/jobs/allAds'
import { useAllAds } from '../../modules/jobs/useAllAds'
import { ALL_SEARCH_NOTE, EXPORT_NOTE, OFF_LIST_NOTE, applyAllControls, classOptions, filterComposed, listNotices, selectableIds } from '../../modules/jobs/jobListView'
import JobDetailDrawer from './JobDetailDrawer'
import JobEmptyState from './JobEmptyState'
import { appliedJobIds } from '../../modules/applications/appliedFilter'
import { filterJobs, getUniqueProviders, getUniqueSites, listedJobs, onListJobs } from '../../modules/jobs/jobFilters'
import { computeJobStats } from '../../modules/jobs/jobStats'
import { selectionFor, toggleAllSelected, toggleSelected } from '../../modules/jobs/jobTableModel'
import { probePipelineApi, runTailor } from '../../modules/jobs/pipelineRunner'
import { searchCountry } from '../../utils/searchCountry'
import { downloadJobsCsv, downloadJobsJson } from '../../modules/jobs/jobExport'
import { usePipelineAutoRefresh } from '../../modules/jobs/usePipelineAutoRefresh'
import { autoLoadJobs } from '../../modules/jobs/autoLoadJobs'
import { derivePipelineStateFromHealth, loadPipelineState, syncPipelineCounts, updatePipelineState } from '../../modules/jobs/pipelineState'
import { overlayTracking, trackerStats } from '../../modules/applications/trackingView'
import { useApplications } from '../../hooks/useApplications'
import { useJobsSync } from '../../hooks/useJobs'
import { loadJobsTab, persistJobsTab } from '../../modules/appNavigation'
import {
  importJobsFromFile,
  loadJobs,
  saveJobs,
  updateFilters,
  updateJobRecord,
  updateJobStatus,
} from '../../modules/jobs/jobStorage'
import { runScoring, loadLatestScoredJobs } from '../../modules/jobs/pipelineRunner'
import { useRescrapeRun } from '../../modules/jobs/useRescrapeRun'
import RescrapeProgress from './RescrapeProgress'
import { withProfileSalaryDefaults } from '../../modules/jobs/jobSalary'
import { loadIntelligence } from '../../modules/intelligence/intelligenceExport'
import { useProfile } from '../../context/ProfileContext'

const JOB_TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'analytics', label: 'Analytics' },
]

export default function JobDiscoveryScreen() {
  const { profile } = useProfile()
  const [state, setState] = useState(() => loadJobs())
  const [activeTab, setActiveTab] = useState(loadJobsTab)
  const [autoLoadNote, setAutoLoadNote] = useState(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [pipelineApiAvailable, setPipelineApiAvailable] = useState(false)
  const [health, setHealth] = useState(null)
  const [pipelineState, setPipelineState] = useState(() => loadPipelineState())
  const [selection, setSelection] = useState(null)
  // Active or All, and All's own filters. Plain state, outside `state.filters`, so changing them saves nothing.
  const [listMode, setListMode] = useState('active')
  const [listClasses, setListClasses] = useState(() => new Set())
  const [seenRecentlyOnly, setSeenRecentlyOnly] = useState(false)
  const [reference, setReference] = useState(() => Date.now())
  const [addInitial, setAddInitial] = useState(null)
  const [selectedJob, setSelectedJob] = useState(null)
  const [bulkRunning, setBulkRunning] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [rerunMsg, setRerunMsg] = useState('')
  const [addJobOpen, setAddJobOpen] = useState(false)
  const [addNote, setAddNote] = useState(null)

  // The old opt-in source checkbox lived here; its value moves to Settings > Sources on the server once.
  useEffect(() => { migrateLegacyDiscoveryOptions() }, [])

  useEffect(() => {
    saveJobs(state)
  }, [state])
  useJobsSync(setState)

  useEffect(() => {
    let cancelled = false
    autoLoadJobs(loadJobs()).then(({ state: next, source }) => {
      if (cancelled) return
      if (source !== 'local') {
        setState(next)
        setAutoLoadNote(`Loaded ${onListJobs(next.jobs).length} jobs from ${source} file`)
      }
    })
    probePipelineApi().then((probe) => {
      if (cancelled) return
      setPipelineApiAvailable(probe.available)
      if (probe.health) {
        setHealth(probe.health)
        setPipelineState(updatePipelineState(derivePipelineStateFromHealth(probe.health, loadJobs().jobs)))
      }
    })
    return () => { cancelled = true }
  }, [])

  // Auto-load and later imports replace the jobs after the probe has answered; counts taken from the jobs follow them.
  useEffect(() => {
    if (!health) return
    const next = syncPipelineCounts(health, state.jobs)
    if (next) setPipelineState(next)
  }, [health, state.jobs])

  usePipelineAutoRefresh({
    enabled: pipelineApiAvailable,
    state,
    onImport: setState,
  })

  const { demoMode } = useDemoBootstrapContext()
  const routeEnabled = pipelineApiAvailable && !demoMode
  const allAds = useAllAds({ enabled: routeEnabled })
  const refetchAllAds = allAds.refetch

  // A new import means a new ledger: Re-scrape, Re-score, auto-refresh and the URL import all set `importedAt`.
  const lastImportedAt = useRef(state.importedAt)
  useEffect(() => {
    if (lastImportedAt.current === state.importedAt) return
    lastImportedAt.current = state.importedAt
    if (routeEnabled) refetchAllAds()
  }, [state.importedAt, routeEnabled, refetchAllAds])

  // The 14 days run to the current date, and the screen can stay open past midnight.
  useEffect(() => {
    const timer = setInterval(() => setReference(Date.now()), 60 * 60 * 1000)
    return () => clearInterval(timer)
  }, [])

  const applications = useApplications()
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
  const applicationStore = applications.status === 'ready' ? applications.store : null
  const appliedIds = useMemo(() => appliedJobIds(applicationStore), [applicationStore])
  // What is stored, as ever: Export and the numbers elsewhere keep reading it.
  const listed = useMemo(() => listedJobs(state.jobs, state.filters), [state.jobs, state.filters])

  // Display only, recomputed from its inputs and never saved. Until the route has answered, Active is today's list.
  const composed = useMemo(
    () => (routeEnabled ? composeJobList({ stored: state.jobs, server: allAds.rows, applications, reference }) : null),
    [routeEnabled, state.jobs, allAds.rows, applications, reference],
  )
  const useComposed = routeEnabled && (allAds.rows !== null || listMode === 'all')
  const composedRows = useMemo(() => {
    if (!useComposed) return null
    const rows = overlayTracking(listMode === 'all' ? composed.all : composed.active, applicationStore, applications.settings)
    // An application needs no stored row: the row says Applied as Job Details does, for display only.
    return rows.map((row) => (row.serverOnly && row.applicationTracking ? { ...row, status: 'applied_manually' } : row))
  }, [useComposed, listMode, composed, applicationStore, applications.settings])
  const shownRows = useMemo(
    () => (useComposed && listMode === 'all' ? applyAllControls(composedRows, { classes: listClasses, recent: seenRecentlyOnly, reference }) : composedRows),
    [useComposed, listMode, composedRows, listClasses, seenRecentlyOnly, reference],
  )
  const baseRows = composedRows ?? listed
  const sites = useMemo(() => getUniqueSites(baseRows), [baseRows])
  const providers = useMemo(() => getUniqueProviders(baseRows), [baseRows])
  const effectiveFilters = useMemo(() => withProfileSalaryDefaults(state.filters, profile?.basicProfile), [state.filters, profile?.basicProfile])
  const filteredJobs = useMemo(() => {
    if (useComposed) return filterComposed(shownRows, effectiveFilters, { appliedJobIds: appliedIds })
    return filterJobs(viewJobs, effectiveFilters, { appliedJobIds: appliedIds })
  }, [useComposed, shownRows, viewJobs, effectiveFilters, appliedIds])
  // Changing a filter starts the selection and the paging again; a sort, Show more or a row's new status do not.
  const filterKey = useMemo(
    () => JSON.stringify([effectiveFilters, listMode, [...listClasses].sort(), seenRecentlyOnly]),
    [effectiveFilters, listMode, listClasses, seenRecentlyOnly],
  )
  const notices = routeEnabled ? listNotices({
    mode: listMode, status: allAds.status, error: allAds.error, meta: allAds.meta, rows: allAds.rows, copies: composed?.copies,
    hasServerOnly: Boolean(composedRows?.some((row) => row.serverOnly)),
  }) : []
  const filtersShown = useComposed ? { ...effectiveFilters, showOffList: false } : effectiveFilters
  const selectedJobIds = selectionFor(selection, filterKey)

  const handleRescrapeFinished = useCallback(async (run) => {
    if (routeEnabled) refetchAllAds() // the ledger may have moved even if the scored file below cannot be read
    if (run?.status === 'cancelled') {
      setRerunMsg('Re-scrape was cancelled. Scoring was skipped; Re-score scores what was collected.')
      return
    }
    if (!run || run.status === 'failed' || run.status === 'interrupted') {
      setRerunMsg(run?.status === 'interrupted' ? 'Re-scrape was interrupted.' : 'Re-scrape failed. Details below.')
      return
    }
    try {
      const jobs = await loadLatestScoredJobs()
      setState((prev) => importJobsFromFile(jobs, prev))
      const p1 = (jobs.jobs || []).filter((j) => j.priority === 'P1').length
      setRerunMsg(`Done — ${jobs.jobs?.length || 0} jobs, ${p1} P1`)
    } catch (e) {
      setRerunMsg(`Error: ${e.message}`)
    }
  }, [routeEnabled, refetchAllAds])

  const rescrape = useRescrapeRun({ enabled: pipelineApiAvailable, onFinished: handleRescrapeFinished })

  const handleRerunDiscovery = useCallback(async () => {
    setRerunning(true)
    setRerunMsg('')
    try {
      const intelligence = loadIntelligence()
      if (!intelligence?.searchStrategy?.jobSpySearchTerms?.length) {
        throw new Error('Run candidate intelligence generation first (Module 2).')
      }
      await rescrape.start({ providers: 'serbia', country: searchCountry(profile, intelligence), intelligence, profile })
    } catch (e) {
      setRerunMsg(`Error: ${e.message}`)
    } finally {
      setRerunning(false)
    }
  }, [profile, rescrape])

  const handleRescore = useCallback(async () => {
    setRerunning(true)
    setRerunMsg('Re-scoring existing jobs…')
    try {
      await runScoring()
      const jobs = await loadLatestScoredJobs()
      setState((prev) => importJobsFromFile(jobs, prev))
      const p1 = (jobs.jobs || []).filter((j) => j.priority === 'P1').length
      setRerunMsg(`Re-scored ${jobs.jobs?.length || 0} jobs — ${p1} P1`)
    } catch (e) {
      setRerunMsg(`Error: ${e.message}`)
    } finally {
      setRerunning(false)
    }
  }, [])

  const handleTabChange = (tab) => {
    setActiveTab(tab)
    persistJobsTab(tab)
  }

  const handleImport = useCallback((next) => {
    setState(next)
  }, [])

  const handleJobAdded = useCallback((job, openDetails, result) => {
    setAddJobOpen(false)
    if (openDetails) openJobPage(job.jobId)
    setAddNote(result.scored
      ? { text: `Added “${job.title}” and scored it.`, jobId: job.jobId, retry: false }
      : { text: `Added “${job.title}” as Unreviewed. ${result.message}`, jobId: job.jobId, retry: !result.noDescription })
  }, [])

  // Opens the form with what the ad gave. Nothing is saved until Save.
  const handleAddFromRow = useCallback((row) => {
    setAddInitial({ title: row.title, company: row.company, jobUrl: row.jobUrl })
    setAddJobOpen(true)
  }, [])

  const handleScoreNow = useCallback(async (jobId, title) => {
    setAddNote((prev) => ({ ...prev, busy: true }))
    const result = await scoreStoredJob(jobId)
    setAddNote(result.ok
      ? { text: `Scored “${title}”.`, jobId, retry: false }
      : { text: result.message, jobId, retry: result.reason !== 'duplicate' })
  }, [])

  const handleUrlImported = useCallback((payload) => {
    setState((prev) => {
      const next = importJobsFromFile(payload, prev)
      return { ...next, meta: payload.meta || next.meta }
    })
  }, [])

  const handleHealthChange = useCallback((h) => {
    setHealth(h)
    setPipelineState(() => updatePipelineState(derivePipelineStateFromHealth(h, state.jobs)))
  }, [state.jobs])

  const handleFilterChange = useCallback((patch) => {
    setState((prev) => updateFilters(prev, patch))
  }, [])

  const handleStatusChange = useCallback((jobId, status) => {
    setState((prev) => ({
      ...prev,
      jobs: updateJobStatus(prev.jobs, jobId, status),
    }))
    setSelectedJob((prev) => (prev?.jobId === jobId ? { ...prev, status } : prev))
  }, [])

  const handleJobUpdated = useCallback((updatedJob) => {
    setState((prev) => ({
      ...prev,
      jobs: updateJobRecord(prev.jobs, updatedJob.jobId, stripDisplayFields(updatedJob)), // the row may be a composed one
    }))
    setSelectedJob((prev) => (prev?.jobId === updatedJob.jobId ? updatedJob : prev))
  }, [])

  const handleToggleSelect = useCallback((jobId) => {
    setSelection((prev) => toggleSelected(prev, filterKey, jobId))
  }, [filterKey])

  const handleToggleSelectAll = useCallback(() => {
    setSelection((prev) => toggleAllSelected(prev, filterKey, selectableIds(filteredJobs)))
  }, [filteredJobs, filterKey])

  const handleBulkTailor = useCallback(async (opts) => {
    setBulkRunning(true)
    try {
      const result = await runTailor({ ...opts, profile })
      if (result.payload) {
        setState((prev) => {
          const next = importJobsFromFile(result.payload, prev)
          return { ...next, meta: result.payload.meta || next.meta }
        })
      }
    } finally {
      setBulkRunning(false)
    }
  }, [profile])

  const handleBulkStatus = useCallback((status) => {
    setState((prev) => ({
      ...prev,
      jobs: prev.jobs.map((j) => (
        selectedJobIds.has(j.jobId) ? { ...j, status } : j
      )),
    }))
  }, [selectedJobIds])

  const handleExportJson = () => {
    downloadJobsJson({
      meta: state.meta,
      jobs: listed,
      exportedAt: new Date().toISOString(),
    })
    setExportOpen(false)
  }

  const handleExportCsv = () => {
    downloadJobsCsv(listed)
    setExportOpen(false)
  }

  const hasJobs = state.jobs.length > 0 || Boolean(allAds.rows?.length && routeEnabled)

  return (
    <div className="space-y-6">
      <Tabs tabs={JOB_TABS} active={activeTab} onChange={handleTabChange} />

      {autoLoadNote && (
        <p className="text-xs text-teal-700 dark:text-teal-300">{autoLoadNote}</p>
      )}

      {activeTab === 'jobs' && (
        <>
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => { setAddInitial(null); setAddJobOpen(true) }}>
              <Plus className="h-4 w-4" />
              Add job
            </Button>
          </div>
          {addJobOpen && <AddJobDialog initial={addInitial} onClose={() => setAddJobOpen(false)} onSaved={handleJobAdded} />}
          {addNote && (
            <div role="status" className="flex flex-wrap items-center gap-2 text-xs text-teal-700 dark:text-teal-300">
              <span>{addNote.text}</span>
              {addNote.retry && (
                <Button variant="secondary" disabled={addNote.busy} onClick={() => handleScoreNow(addNote.jobId, state.jobs.find((j) => j.jobId === addNote.jobId)?.title ?? 'the job')}>
                  {addNote.busy ? 'Scoring…' : 'Score now'}
                </Button>
              )}
              <button type="button" className="underline" onClick={() => setAddNote(null)}>Dismiss</button>
            </div>
          )}

          {pipelineApiAvailable && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 dark:border-stone-800 dark:bg-stone-900">
              <Button onClick={handleRerunDiscovery} disabled={rerunning || rescrape.view.active || !pipelineApiAvailable}>
                {rerunning || rescrape.view.active ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Re-scrape jobs
              </Button>
              <Button variant="secondary" onClick={handleRescore} disabled={rerunning || rescrape.view.active}>
                <RefreshCw className="h-4 w-4" />
                Re-score
              </Button>
              {pipelineApiAvailable && <JobUrlImport onImported={handleUrlImported} compact />}
              {rerunMsg && (
                <p className="ml-1 text-xs text-stone-500 dark:text-stone-400">{rerunMsg}</p>
              )}
              <RescrapeProgress view={rescrape.view} />
            </div>
          )}

          {!hasJobs ? (
            <JobEmptyState />
          ) : (
            <div className="space-y-6 animate-fade-in">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="text-sm text-stone-600 dark:text-stone-400">
                    {filteredJobs.length} of {baseRows.length} jobs shown
                  </p>
                </div>
                  <div className="relative">
                  <Button variant="secondary" title={EXPORT_NOTE} onClick={() => setExportOpen(!exportOpen)}>
                    <MoreHorizontal className="h-4 w-4" />
                    Export
                  </Button>
                  {exportOpen && (
                    <div className="absolute right-0 z-10 mt-1 w-40 rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-stone-700 dark:bg-stone-900">
                      <button type="button" onClick={handleExportJson} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                        <Download className="h-4 w-4" /> JSON, saved rows
                      </button>
                      <button type="button" onClick={handleExportCsv} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                        <Download className="h-4 w-4" /> CSV, saved rows
                      </button>
                    </div>
                  )}
                  </div>
              </div>

              {routeEnabled && (
                <JobListControls
                  mode={listMode}
                  onMode={setListMode}
                  options={listMode === 'all' && composedRows ? classOptions(composedRows) : []}
                  classes={listClasses}
                  onClasses={setListClasses}
                  recent={seenRecentlyOnly}
                  onRecent={setSeenRecentlyOnly}
                  notices={notices}
                  onRetry={refetchAllAds}
                  retrying={allAds.status === 'loading'}
                />
              )}

              <JobFilters filters={filtersShown} searchNote={useComposed && listMode === 'all' ? ALL_SEARCH_NOTE : null} offListDisabledNote={useComposed ? OFF_LIST_NOTE : null} sites={sites} providers={providers} jobs={baseRows} applicationStore={applicationStore} basicProfile={profile?.basicProfile} onChange={handleFilterChange} />
              <BulkActionsBar
                selectedCount={selectedJobIds.size}
                running={bulkRunning}
                jobs={state.jobs}
                selectedJobIds={selectedJobIds}
                onTailorApply={() => handleBulkTailor({ applyOnly: true, limit: 50 })}
                onTailorP1={() => handleBulkTailor({ priority: 'P1', limit: 50 })}
                onMarkSaved={() => handleBulkStatus('saved')}
                onMarkRejected={() => handleBulkStatus('rejected')}
              />
              <JobTable
                jobs={filteredJobs}
                onStatusChange={handleStatusChange}
                apiAvailable={pipelineApiAvailable}
                onJobUpdated={handleJobUpdated}
                selectedJobIds={selectedJobIds}
                filterKey={filterKey}
                classView={useComposed}
                onAddFromRow={handleAddFromRow}
                onToggleSelect={handleToggleSelect}
                onToggleSelectAll={handleToggleSelectAll}
                onJobSelect={setSelectedJob}
              />
            </div>
          )}
        </>
      )}

      {activeTab === 'pipeline' && (
        <div className="space-y-6">
          <PipelineHealthPanel health={health} pipelineState={pipelineState} />
          <PipelineOrchestrator state={state} onImport={handleImport} onHealthChange={handleHealthChange} />
          <JobImportPanel state={state} onImport={handleImport} />
        </div>
      )}

      {activeTab === 'analytics' && (
        <div className="space-y-6">
          {hasJobs ? (
            <>
              <ApplicationDashboard stats={stats} />
              <JobDiscoverySummary stats={stats} meta={state.meta} />
            </>
          ) : (
            <p className="text-sm text-stone-600 dark:text-stone-400">No job data yet. Run the pipeline or import jobs.</p>
          )}
        </div>
      )}

      <JobDetailDrawer
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        apiAvailable={pipelineApiAvailable}
      />
    </div>
  )
}
