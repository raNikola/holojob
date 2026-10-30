import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Loader2, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import Button from '../ui/Button'
import Tabs from '../ui/Tabs'
import JobDiscoverySummary from './JobDiscoverySummary'
import PipelineHealthPanel from './PipelineHealthPanel'
import PipelineOrchestrator from './PipelineOrchestrator'
import JobImportPanel from './JobImportPanel'
import JobUrlImport from './JobUrlImport'
import DiscoverySourceOptions from './DiscoverySourceOptions'
import { discoveryProviders, loadDiscoveryOptions, saveDiscoveryOptions } from '../../modules/jobs/discoveryOptions'
import AddJobDialog from './AddJobDialog'
import { openJobPage } from '../../modules/jobs/jobRoute'
import { scoreStoredJob } from '../../modules/jobs/manualScoring'
import ApplicationDashboard from './ApplicationDashboard'
import JobFilters from './JobFilters'
import BulkActionsBar from './BulkActionsBar'
import JobTable from './JobTable'
import JobDetailDrawer from './JobDetailDrawer'
import JobEmptyState from './JobEmptyState'
import { appliedJobIds } from '../../modules/applications/appliedFilter'
import { filterJobs, getUniqueProviders, getUniqueSites } from '../../modules/jobs/jobFilters'
import { computeJobStats } from '../../modules/jobs/jobStats'
import { probePipelineApi, runTailor } from '../../modules/jobs/pipelineRunner'
import { searchCountry } from '../../utils/searchCountry'
import { downloadJobsCsv, downloadJobsJson } from '../../modules/jobs/jobExport'
import { usePipelineAutoRefresh } from '../../modules/jobs/usePipelineAutoRefresh'
import { autoLoadJobs } from '../../modules/jobs/autoLoadJobs'
import { derivePipelineStateFromHealth, loadPipelineState, updatePipelineState } from '../../modules/jobs/pipelineState'
import { overlayTracking } from '../../modules/applications/trackingView'
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
import { runDiscovery, runScoring, loadLatestScoredJobs } from '../../modules/jobs/pipelineRunner'
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
  const [selectedJobIds, setSelectedJobIds] = useState([])
  const [selectedJob, setSelectedJob] = useState(null)
  const [bulkRunning, setBulkRunning] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [discoveryOptions, setDiscoveryOptions] = useState(loadDiscoveryOptions)
  const [rerunMsg, setRerunMsg] = useState('')
  const [addJobOpen, setAddJobOpen] = useState(false)
  const [addNote, setAddNote] = useState(null)

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
        setAutoLoadNote(`Loaded ${next.jobs.length} jobs from ${source} file`)
      }
    })
    probePipelineApi().then((probe) => {
      if (cancelled) return
      setPipelineApiAvailable(probe.available)
      if (probe.health) {
        setHealth(probe.health)
        setPipelineState(updatePipelineState(derivePipelineStateFromHealth(probe.health, state.jobs)))
      }
    })
    return () => { cancelled = true }
  }, [])

  usePipelineAutoRefresh({
    enabled: pipelineApiAvailable,
    state,
    onImport: setState,
  })

  const applications = useApplications()
  // Tracking comes from the application store; `state.jobs` stays as saved and is what gets persisted.
  const viewJobs = useMemo(
    () => overlayTracking(state.jobs, applications.status === 'ready' ? applications.store : null, applications.settings),
    [state.jobs, applications.status, applications.store, applications.settings],
  )
  const stats = useMemo(() => computeJobStats(viewJobs), [viewJobs])
  const applicationStore = applications.status === 'ready' ? applications.store : null
  const appliedIds = useMemo(() => appliedJobIds(applicationStore), [applicationStore])
  const sites = useMemo(() => getUniqueSites(state.jobs), [state.jobs])
  const providers = useMemo(() => getUniqueProviders(state.jobs), [state.jobs])
  const effectiveFilters = useMemo(() => withProfileSalaryDefaults(state.filters, profile?.basicProfile), [state.filters, profile?.basicProfile])
  const filteredJobs = useMemo(() => {
    return filterJobs(viewJobs, effectiveFilters, { appliedJobIds: appliedIds })
  }, [viewJobs, effectiveFilters, appliedIds])

  const handleRerunDiscovery = useCallback(async () => {
    setRerunning(true)
    setRerunMsg('Discovering new jobs…')
    try {
      const intelligence = loadIntelligence()
      if (!intelligence?.searchStrategy?.jobSpySearchTerms?.length) {
        throw new Error('Run candidate intelligence generation first (Module 2).')
      }
      await runDiscovery({ providers: discoveryProviders(discoveryOptions), country: searchCountry(profile, intelligence), intelligence, profile })
      setRerunMsg('Scoring jobs…')
      await runScoring()
      const jobs = await loadLatestScoredJobs()
      setState((prev) => importJobsFromFile(jobs, prev))
      const p1 = (jobs.jobs || []).filter((j) => j.priority === 'P1').length
      setRerunMsg(`Done — ${jobs.jobs?.length || 0} jobs, ${p1} P1`)
    } catch (e) {
      setRerunMsg(`Error: ${e.message}`)
    } finally {
      setRerunning(false)
    }
  }, [profile, discoveryOptions])

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
      jobs: updateJobRecord(prev.jobs, updatedJob.jobId, updatedJob),
    }))
    setSelectedJob((prev) => (prev?.jobId === updatedJob.jobId ? updatedJob : prev))
  }, [])

  const handleToggleSelect = useCallback((jobId) => {
    setSelectedJobIds((prev) => (
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId]
    ))
  }, [])

  const handleToggleSelectAll = useCallback(() => {
    const ids = filteredJobs.map((j) => j.jobId)
    setSelectedJobIds((prev) => (prev.length === ids.length ? [] : ids))
  }, [filteredJobs])

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
        selectedJobIds.includes(j.jobId) ? { ...j, status } : j
      )),
    }))
  }, [selectedJobIds])

  const handleExportJson = () => {
    downloadJobsJson({
      meta: state.meta,
      jobs: state.jobs,
      exportedAt: new Date().toISOString(),
    })
    setExportOpen(false)
  }

  const handleExportCsv = () => {
    downloadJobsCsv(state.jobs)
    setExportOpen(false)
  }

  const hasJobs = state.jobs.length > 0

  return (
    <div className="space-y-6">
      <Tabs tabs={JOB_TABS} active={activeTab} onChange={handleTabChange} />

      {autoLoadNote && (
        <p className="text-xs text-teal-700 dark:text-teal-300">{autoLoadNote}</p>
      )}

      {activeTab === 'jobs' && (
        <>
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => setAddJobOpen(true)}>
              <Plus className="h-4 w-4" />
              Add job
            </Button>
          </div>
          {addJobOpen && <AddJobDialog onClose={() => setAddJobOpen(false)} onSaved={handleJobAdded} />}
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
              <Button onClick={handleRerunDiscovery} disabled={rerunning || !pipelineApiAvailable}>
                {rerunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                Re-scrape jobs
              </Button>
              <DiscoverySourceOptions
                options={discoveryOptions}
                disabled={rerunning}
                onChange={(next) => { setDiscoveryOptions(next); saveDiscoveryOptions(next) }}
              />
              <Button variant="secondary" onClick={handleRescore} disabled={rerunning}>
                <RefreshCw className="h-4 w-4" />
                Re-score
              </Button>
              {pipelineApiAvailable && <JobUrlImport onImported={handleUrlImported} compact />}
              {rerunMsg && (
                <p className="ml-1 text-xs text-stone-500 dark:text-stone-400">{rerunMsg}</p>
              )}
            </div>
          )}

          {!hasJobs ? (
            <JobEmptyState />
          ) : (
            <div className="space-y-6 animate-fade-in">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="text-sm text-stone-600 dark:text-stone-400">
                    {filteredJobs.length} of {state.jobs.length} jobs shown
                  </p>
                </div>
                  <div className="relative">
                  <Button variant="secondary" onClick={() => setExportOpen(!exportOpen)}>
                    <MoreHorizontal className="h-4 w-4" />
                    Export
                  </Button>
                  {exportOpen && (
                    <div className="absolute right-0 z-10 mt-1 w-40 rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-stone-700 dark:bg-stone-900">
                      <button type="button" onClick={handleExportJson} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                        <Download className="h-4 w-4" /> JSON
                      </button>
                      <button type="button" onClick={handleExportCsv} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                        <Download className="h-4 w-4" /> CSV
                      </button>
                    </div>
                  )}
                  </div>
              </div>

              <JobFilters filters={effectiveFilters} sites={sites} providers={providers} jobs={state.jobs} applicationStore={applicationStore} basicProfile={profile?.basicProfile} onChange={handleFilterChange} />
              <BulkActionsBar
                selectedCount={selectedJobIds.length}
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
