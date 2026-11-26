import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, Loader2, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Card from '../ui/Card'
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
import { isClosedAd } from '../../modules/jobs/jobHistory'
import { tierCounts } from '../../modules/jobs/fitTier'
import { useAllAds } from '../../modules/jobs/useAllAds'
import { useServerList } from '../../modules/jobs/useServerList'
import { fetchListCounts, listRows } from '../../modules/jobs/jobListClient'
import { adoptRows, applyWorkedRows, fetchWorkedRows, refreshWorkedRows } from '../../modules/jobs/workedRows'
import { ensureApiAvailable } from '../../utils/apiAvailability'
import { isServerListActive } from '../../modules/jobs/serverListSwitch'
import { dayOf } from '../../modules/jobs/jobDeadline'
import { useTableSort } from '../ui/SortableTh'
import { useActiveWindowDays } from '../../modules/jobs/useActiveWindowDays'
import { GATE_SETTINGS_SAVED_EVENT } from '../../modules/ai/gateClient'
import { ALL_SEARCH_NOTE, EXPORT_NOTE, OFF_LIST_NOTE, applyAllControls, classOptions, filterComposed, listNotices, selectableIds } from '../../modules/jobs/jobListView'
import JobDetailDrawer from './JobDetailDrawer'
import JobEmptyState from './JobEmptyState'
import { appliedJobIds } from '../../modules/applications/appliedFilter'
import { filterJobs, getUniqueProviders, getUniqueSites, hiddenAsNotOnBoard, listedJobs, onListJobs } from '../../modules/jobs/jobFilters'
import { computeJobStats } from '../../modules/jobs/jobStats'
import { DEFAULT_SORT, SORT_COLUMNS, selectionFor, toggleAllSelected, toggleSelected } from '../../modules/jobs/jobTableModel'
import { probePipelineApi, runTailor } from '../../modules/jobs/pipelineRunner'
import TailorConfirmDialog from './TailorConfirmDialog'
import { searchCountry } from '../../utils/searchCountry'
import { downloadJobsCsv, downloadJobsJson } from '../../modules/jobs/jobExport'
import { usePipelineAutoRefresh } from '../../modules/jobs/usePipelineAutoRefresh'
import { autoLoadJobs } from '../../modules/jobs/autoLoadJobs'
import { derivePipelineStateFromHealth, loadPipelineState, syncPipelineCounts, updatePipelineState } from '../../modules/jobs/pipelineState'
import { overlayTracking, trackerStats } from '../../modules/applications/trackingView'
import { useApplications } from '../../hooks/useApplications'
import QuickApplyDialog from './QuickApplyDialog'
import { useJobState } from '../../hooks/useJobState'
import { jobMatchKey } from '../../modules/jobs/jobStorage'
import { PENDING_NOTICE, pendingRows, withServerState, writeJobState, writeJobStates } from '../../modules/jobs/jobStateClient'
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
import RescrapeProgress, { RescrapeEventLog } from './RescrapeProgress'
import ActivityScreen from '../activity/ActivityScreen'
import { cancelledText, currentSource } from '../../modules/jobs/rescrapeRun'
import { withProfileSalaryDefaults } from '../../modules/jobs/jobSalary'
import { loadIntelligence } from '../../modules/intelligence/intelligenceExport'
import { useProfile } from '../../context/ProfileContext'
import { HeaderPortal } from '../layout/HeaderSlot'
import { TOAST_AUTO_HIDE_MS, Toast, ToastStack } from '../ui/Toast'

/**
 * The notices above the server's list. A refusal is shown with its own words (a request that is too large says how many ads and what to do), a list that changed
 * says so, and the rest are the local list's notices on the server's counts.
 */
function serverNotices({ list, mode, unlisted, hasServerOnly }) {
  const notices = []
  if (list.error?.tooLarge) {
    notices.push({ kind: 'error', text: list.error.message }) // its own words: how many ads, what was not done, what to do
  } else if (list.error) {
    // The same words as the route's list has: what failed, and that what is saved in this browser is shown and nothing was changed.
    notices.push(...listNotices({ mode, status: 'error', error: list.error.message, meta: null, rows: list.rows.length ? list.rows : null, copies: null, hasServerOnly, unlisted }))
  }
  if (list.notice) notices.push({ kind: 'info', text: list.notice })
  if (!list.error) {
    const loaded = list.status === 'ready' ? list.rows : null
    notices.push(...listNotices({ mode, status: 'ready', error: null, meta: list.meta, rows: loaded, copies: list.counts?.copies, hasServerOnly, unlisted }))
  }
  return notices
}

// What the screen does after a scoring run, and when it loads. With the server's list the whole scored list is NOT loaded into the browser: the rows the browser
// holds are brought up to date from the server (`workedRows.js`), `adopt` are rows the owner has just made theirs (tailored documents, a job imported by its
// address), and the numbers for the toast come from the server. Without it (demo data, no API) the scored file is imported, as ever.
async function importLatestRun({ serverList, setState, adopt = [] }) {
  if (!serverList) {
    const jobs = await loadLatestScoredJobs()
    setState((prev) => importJobsFromFile(jobs, prev))
    return { total: jobs.jobs?.length || 0, strong: tierCounts(jobs.jobs, (j) => !isClosedAd(j)).strong }
  }
  const stored = loadJobs().jobs
  const ids = [...new Set([...stored.map((job) => job.jobId), ...adopt.map((row) => row.jobId)])]
  const got = ids.length ? await fetchWorkedRows(ids) : { ok: true, answer: { rows: [], missing: [] } }
  if (!got.ok) throw new Error(got.error)
  setState((prev) => applyWorkedRows({ ...prev, jobs: adoptRows(prev.jobs, adopt) }, got.answer))
  const counts = await fetchListCounts({ stored: adoptRows(stored, adopt) })
  if (!counts.ok) throw new Error(counts.message)
  return { total: counts.counts.stats.total, strong: counts.counts.stats.strong }
}

/** On load with the server's list: the rows the browser holds are brought up to date from the server. Nothing else is loaded. */
async function refreshStoredRowsOnLoad(existing) {
  if (!(await ensureApiAvailable())) return { state: existing, source: 'local' }
  const probe = await probePipelineApi()
  if (!probe.available) return { state: existing, source: 'local' }
  const refreshed = await refreshWorkedRows(existing)
  return refreshed.error || !refreshed.changed ? { state: existing, source: 'local' } : { state: refreshed.state, source: 'refreshed' }
}

/** The rows of a scoring run's file that carry the owner's tailored documents: those ads are the owner's work now. */
const tailoredRows = (payload) => (payload?.jobs ?? []).filter((job) => Object.keys(job?.tailoredAssets ?? {}).length > 0)

const JOB_TABS = [
  { id: 'jobs', label: 'Jobs' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'activity', label: 'Activity' },
]

export default function JobDiscoveryScreen() {
  const { profile } = useProfile()
  const { demoMode } = useDemoBootstrapContext()
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
  const [applyJob, setApplyJob] = useState(null) // the job whose Applied form is open; nothing is written until it is saved
  const [bulkRunning, setBulkRunning] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  // Which button's work this page is waiting on ('scrape' | 'score'), and the end-of-run toast (errors stay until closed).
  const [busyAction, setBusyAction] = useState(null)
  const [runToast, setRunToast] = useState(null)
  const [addJobOpen, setAddJobOpen] = useState(false)
  const [addNote, setAddNote] = useState(null)
  // List notices closed (or timed out) in this visit, by text; a notice whose text changes shows again.
  const [closedNotices, setClosedNotices] = useState(() => new Set())
  const closeNotice = useCallback((text) => setClosedNotices((prev) => new Set(prev).add(text)), [])

  // The old opt-in source checkbox lived here; its value moves to Settings > Sources on the server once.
  useEffect(() => { migrateLegacyDiscoveryOptions() }, [])

  useEffect(() => {
    saveJobs(state)
  }, [state])
  useJobsSync(setState)

  useEffect(() => {
    let cancelled = false
    const load = isServerListActive() && !demoMode ? refreshStoredRowsOnLoad(loadJobs()) : autoLoadJobs(loadJobs())
    load.then(({ state: next, source }) => {
      if (cancelled) return
      if (source !== 'local') {
        setState(next)
        if (source !== 'refreshed') setAutoLoadNote(`Loaded ${onListJobs(next.jobs).length} jobs from ${source} file`)
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
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- read once, when the screen opens (demo mode is settled by then)

  // Auto-load and later imports replace the jobs after the probe has answered; counts taken from the jobs follow them.
  useEffect(() => {
    if (!health) return
    const next = syncPipelineCounts(health, state.jobs)
    if (next) setPipelineState(next)
  }, [health, state.jobs])


  const routeEnabled = pipelineApiAvailable && !demoMode
  // The server's list (docs/redesign/JOBS_LIST_SERVER_PLAN.md): the server filters, orders, pages and counts, and the browser holds the pages in memory. Demo data and no
  // API have no server list, and keep working from the browser's own rows as before.
  const serverOn = routeEnabled && isServerListActive()
  // The Active period is a Settings field. The server's list reads it on the server and says which it used; only the list the browser works out itself needs it here.
  const activeWindowDays = useActiveWindowDays({ enabled: !serverOn })
  const allAds = useAllAds({ enabled: routeEnabled && !serverOn })
  const refetchAllAds = allAds.refetch


  // The 14 days run to the current date, and the screen can stay open past midnight.
  useEffect(() => {
    const timer = setInterval(() => setReference(Date.now()), 60 * 60 * 1000)
    return () => clearInterval(timer)
  }, [])

  const applications = useApplications()
  const jobState = useJobState()
  const [statusError, setStatusError] = useState(null)
  // Tracking comes from the application store; `state.jobs` stays as saved and is what gets persisted.
  const viewJobs = useMemo(
    () => overlayTracking(withServerState(state.jobs, jobState.doc), applications.status === 'ready' ? applications.store : null, applications.settings),
    [state.jobs, jobState.doc, applications.status, applications.store, applications.settings],
  )
  // Browser rows the server does not hold yet stay visible here, and this says so until they are imported (Settings).
  const pending = useMemo(() => pendingRows(state.jobs, jobState.doc).length, [state.jobs, jobState.doc])
  const localStats = useMemo(
    // The tracker cards count applications from the store, whether or not their ad still has a row.
    () => ({ ...computeJobStats(viewJobs), ...trackerStats(applications.status === 'ready' ? applications.store : null, applications.settings) }),
    [viewJobs, applications.status, applications.store, applications.settings],
  )
  const applicationStore = applications.status === 'ready' ? applications.store : null
  const appliedIds = useMemo(() => appliedJobIds(applicationStore), [applicationStore])
  // What is stored, as ever: Export and the numbers elsewhere keep reading it.
  const listed = useMemo(() => listedJobs(state.jobs, state.filters), [state.jobs, state.filters])

  const effectiveFilters = useMemo(() => withProfileSalaryDefaults(state.filters, profile?.basicProfile), [state.filters, profile?.basicProfile])

  // The server's list: one request for the query and the browser's own rows (the allowlist in extraRows.js), pages kept in memory only, the sort asked of the server.
  const [tableSort, onTableSort] = useTableSort(DEFAULT_SORT, SORT_COLUMNS)
  const listRequest = useMemo(
    () => ({ stored: state.jobs, mode: listMode, filters: effectiveFilters, classes: [...listClasses], recent: seenRecentlyOnly, sort: tableSort, today: dayOf(reference) }),
    [state.jobs, listMode, effectiveFilters, listClasses, seenRecentlyOnly, tableSort, reference],
  )
  const serverList = useServerList({ enabled: serverOn, request: listRequest })
  // The server's list is shown from its first answer on (empty while it loads a new query). Until then, and when it cannot be made at all, the rows saved in this
  // browser are shown with the notice and a way to try again, as the route's list always did: a list that failed is never an empty one.
  const serverShown = serverOn && (serverList.status === 'ready' || serverList.status === 'loading')
  const serverRows = useMemo(() => (serverShown ? listRows(serverList.rows, state.jobs) : null), [serverShown, serverList.rows, state.jobs])
  const facets = serverShown ? serverList.counts?.facets ?? null : null
  const stats = serverShown && serverList.counts ? serverList.counts.stats : localStats
  const refreshList = useCallback(() => (serverOn ? serverList.refresh() : refetchAllAds()), [serverOn, serverList.refresh, refetchAllAds]) // eslint-disable-line react-hooks/exhaustive-deps

  // The page size and the Active period are Settings: saving them changes the list, so it is read again where it stands.
  useEffect(() => {
    if (!serverOn) return undefined
    window.addEventListener(GATE_SETTINGS_SAVED_EVENT, refreshList)
    return () => window.removeEventListener(GATE_SETTINGS_SAVED_EVENT, refreshList)
  }, [serverOn, refreshList])

  // A new import means a new ledger: Re-scrape, Re-score, auto-refresh and the URL import all set `importedAt`.
  const lastImportedAt = useRef(state.importedAt)
  useEffect(() => {
    if (lastImportedAt.current === state.importedAt) return
    lastImportedAt.current = state.importedAt
    if (routeEnabled) refreshList()
  }, [state.importedAt, routeEnabled, refreshList])

  usePipelineAutoRefresh({
    enabled: pipelineApiAvailable,
    state,
    onImport: setState,
    refreshRows: isServerListActive() && !demoMode ? async () => { await importLatestRun({ serverList: true, setState }); refreshList() } : null,
  })

  // Display only, recomputed from its inputs and never saved. Until the route has answered, Active is today's list.
  const composed = useMemo(
    () => (routeEnabled && !serverOn ? composeJobList({ stored: state.jobs, server: allAds.rows, applications, reference, activeWindowDays, jobStateDoc: jobState.doc }) : null),
    [routeEnabled, serverOn, state.jobs, allAds.rows, applications, reference, activeWindowDays, jobState.doc],
  )
  const useComposed = serverShown || (!serverOn && routeEnabled && (allAds.rows !== null || listMode === 'all'))
  const composedRows = useMemo(() => {
    if (!useComposed || serverOn) return null
    const rows = overlayTracking(withServerState(listMode === 'all' ? composed.all : composed.active, jobState.doc), applicationStore, applications.settings)
    // An application needs no stored row: the row says Applied as Job Details does, for display only.
    return rows.map((row) => (row.serverOnly && row.applicationTracking ? { ...row, status: 'applied_manually' } : row))
  }, [useComposed, serverOn, listMode, composed, applicationStore, applications.settings, jobState.doc])
  const shownRows = useMemo(
    () => (useComposed && !serverOn && listMode === 'all' ? applyAllControls(composedRows, { classes: listClasses, recent: seenRecentlyOnly, reference, windowDays: activeWindowDays }) : composedRows),
    [useComposed, serverOn, listMode, composedRows, listClasses, seenRecentlyOnly, reference, activeWindowDays],
  )

  const baseRows = useMemo(() => (serverShown ? (serverRows ?? []) : (composedRows ?? listed)), [serverShown, serverRows, composedRows, listed])
  const sites = useMemo(() => (serverShown ? facets?.sites ?? [] : getUniqueSites(baseRows)), [serverShown, facets, baseRows])
  const providers = useMemo(() => (serverShown ? facets?.providers ?? [] : getUniqueProviders(baseRows)), [serverShown, facets, baseRows])
  const filteredJobs = useMemo(() => {
    if (serverShown) return serverRows ?? [] // the server has filtered and ordered them
    // All is the full list (its class filters find the ads the board no longer lists); only Active leaves them out by default.
    if (useComposed) return filterComposed(shownRows, listMode === 'all' ? { ...effectiveFilters, showNotOnBoard: true } : effectiveFilters, { appliedJobIds: appliedIds })
    // Until the route answers, Active still leaves closed ads out. Demo mode and no API have no All list to find them in.
    return filterJobs(routeEnabled ? viewJobs.filter((job) => !isClosedAd(job)) : viewJobs, effectiveFilters, { appliedJobIds: appliedIds })
  }, [serverShown, serverRows, useComposed, listMode, shownRows, viewJobs, effectiveFilters, appliedIds, routeEnabled])
  // Ads the default list leaves out because the board no longer lists them (the notice says how many, and where to find them).
  const notOnBoardHidden = useMemo(
    () => (serverShown ? serverList.counts?.notOnBoardHidden ?? 0 : (useComposed && listMode === 'active' ? shownRows.filter((job) => hiddenAsNotOnBoard(job, effectiveFilters)).length : 0)),
    [serverShown, serverList.counts, useComposed, listMode, shownRows, effectiveFilters],
  )
  // Changing a filter starts the selection and the paging again; a sort, Show more or a row's new status do not.
  const filterKey = useMemo(
    () => JSON.stringify([effectiveFilters, listMode, [...listClasses].sort(), seenRecentlyOnly]),
    [effectiveFilters, listMode, listClasses, seenRecentlyOnly],
  )
  const notices = serverOn ? serverNotices({ list: serverList, mode: listMode, unlisted: notOnBoardHidden, hasServerOnly: Boolean(serverRows?.some((row) => row.serverOnly)) }) : routeEnabled ? listNotices({
    mode: listMode, status: allAds.status, error: allAds.error, meta: allAds.meta, rows: allAds.rows, copies: composed?.copies,
    hasServerOnly: Boolean(composedRows?.some((row) => row.serverOnly)), unlisted: notOnBoardHidden,
  }) : []
  const filtersShown = useComposed ? { ...effectiveFilters, showOffList: false } : effectiveFilters
  const selectedJobIds = selectionFor(selection, filterKey)

  const handleRescrapeFinished = useCallback(async (run) => {
    if (routeEnabled) refreshList() // the ledger may have moved even if the scored file below cannot be read
    if (run?.status === 'cancelled') {
      setRunToast({ kind: 'warn', text: cancelledText(run.cancel).replace('The last run was cancelled.', 'Re-scrape was cancelled.') })
      return
    }
    if (run?.import?.nothingSaved === 'no_usable_source') {
      setRunToast({ kind: 'warn', text: 'Re-scrape found nothing usable: no source gave a usable result, so the list was not changed. The event log is in the Activity tab.' })
      return
    }
    if (!run || run.status === 'failed' || run.status === 'interrupted') {
      setRunToast({ kind: 'error', text: run?.status === 'interrupted' ? 'Re-scrape was interrupted. It is not resumed: start it again when you want fresh jobs.' : 'Re-scrape failed. The event log is in the Activity tab.' })
      return
    }
    try {
      const { total, strong } = await importLatestRun({ serverList: serverOn, setState })
      if (serverOn) refreshList()
      const waiting = run.status === 'waiting' ? run.paid?.waiting : null
      setRunToast(waiting !== null && waiting !== undefined
        ? { kind: 'warn', text: `Re-scrape finished, but ${waiting} ${waiting === 1 ? 'ad is' : 'ads are'} still waiting: a limit stopped the paid steps (${total} jobs, ${strong} Strong fit). The next Re-scrape continues; Activity says which limit.` }
        : { kind: 'success', text: `Re-scrape done: ${total} jobs, ${strong} Strong fit.` })
    } catch (e) {
      setRunToast({ kind: 'error', text: `Re-scrape finished, but the new jobs could not be loaded: ${e.message}` })
    }
  }, [routeEnabled, serverOn, refreshList])

  const [skipJobspyOnce, setSkipJobspyOnce] = useState(false)
  const rescrape = useRescrapeRun({ enabled: pipelineApiAvailable, onFinished: handleRescrapeFinished })

  const handleRerunDiscovery = async () => {
    setRerunning(true)
    setBusyAction('scrape')
    setRunToast(null)
    try {
      const intelligence = loadIntelligence()
      if (!intelligence?.searchStrategy?.jobSpySearchTerms?.length) {
        throw new Error('Run candidate intelligence generation first (Module 2).')
      }
      await rescrape.start({
        providers: 'serbia', country: searchCountry(profile, intelligence), intelligence, profile,
        ...(skipJobspyOnce ? { excludeProviders: ['jobspy'] } : {}), // this run only; the saved switch is not touched
      })
      setSkipJobspyOnce(false) // "this time" means one run
    } catch (e) {
      setRunToast({ kind: 'error', text: `Re-scrape did not start: ${e.message}` })
    } finally {
      setRerunning(false)
      setBusyAction(null)
    }
  }

  const handleRescore = useCallback(async () => {
    setRerunning(true)
    setBusyAction('score')
    setRunToast(null)
    try {
      const run = await runScoring()
      const { total, strong } = await importLatestRun({ serverList: serverOn, setState })
      refreshList()
      const text = `Re-scored ${total} jobs, ${strong} Strong fit.`
      setRunToast(run?.keptSynced === false
        ? { kind: 'warn', text: `${text} Your kept and applied ads could not be registered for scoring, so some may be missing from this run. Check the server, then Re-score again.` }
        : { kind: 'success', text })
    } catch (e) {
      setRunToast({ kind: 'error', text: `Re-score failed: ${e.message}` })
    } finally {
      setRerunning(false)
      setBusyAction(null)
      // A finished scoring run settles "scoring behind"; without this the banner stays after a cancelled Re-scrape.
      rescrape.refresh()
    }
  }, [rescrape, serverOn, refreshList])

  const scrapeRunning = rescrape.view.active || (rerunning && busyAction === 'scrape')
  const scoreRunning = rerunning && busyAction === 'score'
  const runningSource = rescrape.view.active ? currentSource(rescrape.view.events) : ''

  const handleTabChange = (tab) => {
    setActiveTab(tab)
    persistJobsTab(tab)
  }

  // A finished pipeline run (or "load scored jobs") with the server's list: the browser's rows are brought up to date and the list is read again.
  const handleRefreshFromRun = useCallback(async (payload) => {
    try {
      await importLatestRun({ serverList: true, setState, adopt: tailoredRows(payload) })
      refreshList()
    } catch (e) {
      setRunToast({ kind: 'error', text: `The new jobs could not be loaded: ${e.message}` })
    }
  }, [refreshList])

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

  const handleUrlImported = useCallback((payload, imported) => {
    if (serverOn) {
      // The ads the owner imported by address are theirs now; the rest of the scored list stays on the server.
      const ids = new Set((imported ?? []).map((job) => job.jobId))
      setState((prev) => ({ ...prev, jobs: adoptRows(prev.jobs, (payload?.jobs ?? []).filter((job) => ids.has(job.jobId))), meta: payload?.meta || prev.meta, importedAt: new Date().toISOString() }))
      return
    }
    setState((prev) => {
      const next = importJobsFromFile(payload, prev)
      return { ...next, meta: payload.meta || next.meta }
    })
  }, [serverOn])

  const handleHealthChange = useCallback((h) => {
    setHealth(h)
    setPipelineState(() => updatePipelineState(derivePipelineStateFromHealth(h, state.jobs)))
  }, [state.jobs])

  const handleFilterChange = useCallback((patch) => {
    setState((prev) => updateFilters(prev, patch))
  }, [])

  // The server is written first. A failed write (unreachable or refused) changes nothing, here or in the browser's list.
  const handleStatusChange = useCallback(async (jobId, status) => {
    const stored = state.jobs.find((j) => j.jobId === jobId)
    const job = stored ?? (serverShown ? serverRows?.find((row) => row.jobId === jobId) : null)
    if (!job) return
    try {
      await writeJobState(job, { status })
      setStatusError(null)
    } catch (e) {
      // The server is the single source of truth: any failed write (unreachable included) changes nothing and says so.
      setStatusError(`The status was not saved: ${e.message}`)
      return
    }
    // A row only the server holds has no stored copy to change: the server's job state is the record, and the list is read again where it stands.
    if (stored) {
      setState((prev) => ({
        ...prev,
        jobs: updateJobStatus(prev.jobs, jobId, status),
      }))
    } else {
      refreshList()
    }
    setSelectedJob((prev) => (prev?.jobId === jobId ? { ...prev, status } : prev))
  }, [state.jobs, serverShown, serverRows, refreshList])

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

  // The match keys select-all got for ads this browser has no row for (`{ jobId: key }`).
  const serverKeys = useRef({})

  const handleToggleSelectAll = useCallback(async () => {
    if (!serverShown) {
      setSelection((prev) => toggleAllSelected(prev, filterKey, selectableIds(filteredJobs)))
      return
    }
    // The ads of every page, not only the ones loaded: the server names them.
    const everyone = await serverList.ids()
    if (everyone.error) {
      setStatusError(`Select all did not work: ${everyone.error}`)
      return
    }
    // Every ad of the list, the ones only the server holds too: a status goes to the server's job state. Their match keys are kept for the write.
    serverKeys.current = { ...serverKeys.current, ...everyone.keys }
    setSelection((prev) => toggleAllSelected(prev, filterKey, everyone.selectableIds))
  }, [serverShown, serverList.ids, filteredJobs, filterKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // The bulk buttons only open the confirm dialog; `runBulkTailor` runs when its own button is pressed.
  const [tailorAsk, setTailorAsk] = useState(null)
  const handleBulkTailor = useCallback((opts) => setTailorAsk(opts), [])

  const runBulkTailor = useCallback(async (opts, mode) => {
    setTailorAsk(null)
    setBulkRunning(true)
    try {
      const result = await runTailor({ ...opts, profile, ...mode })
      if (result.payload && serverOn) {
        // The documents just made are the owner's work: those ads are taken into the browser's list, the rest of the scored list stays on the server.
        setState((prev) => ({ ...prev, jobs: adoptRows(prev.jobs, tailoredRows(result.payload)), meta: result.payload.meta || prev.meta, importedAt: new Date().toISOString() }))
      } else if (result.payload) {
        setState((prev) => {
          const next = importJobsFromFile(result.payload, prev)
          return { ...next, meta: result.payload.meta || next.meta }
        })
      }
    } finally {
      setBulkRunning(false)
    }
  }, [profile, serverOn])

  // Mark saved / rejected on every selected ad, the server-only ones included: one batched request to the server's job state, written first like a single row's.
  // A failed write changes nothing. Rows stored in the browser follow the server's answer; the rest are read again from the server.
  const handleBulkStatus = useCallback(async (status) => {
    const storedIds = new Set(state.jobs.map((job) => job.jobId))
    const known = new Map([...(serverRows ?? []), ...filteredJobs].map((row) => [row.jobId, row]))
    const items = []
    for (const jobId of selectedJobIds) {
      const row = state.jobs.find((job) => job.jobId === jobId) ?? known.get(jobId)
      const key = row ? jobMatchKey(row) : serverKeys.current[jobId]
      if (key) items.push({ jobId, key })
    }
    if (!items.length) return
    setBulkRunning(true)
    try {
      await writeJobStates(items, { status })
      setStatusError(null)
    } catch (e) {
      setStatusError(`The status was not saved: ${e.message}`)
      return
    } finally {
      setBulkRunning(false)
    }
    setState((prev) => ({ ...prev, jobs: prev.jobs.map((j) => (selectedJobIds.has(j.jobId) ? { ...j, status } : j)) }))
    if (items.some((item) => !storedIds.has(item.jobId))) refreshList()
  }, [state.jobs, serverRows, filteredJobs, selectedJobIds, refreshList])

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

  const hasJobs = serverOn
    ? state.jobs.length > 0 || serverList.status === 'loading' || serverList.total > 0 || (serverList.counts?.baseTotal ?? 0) > 0
    : state.jobs.length > 0 || Boolean(allAds.rows?.length && routeEnabled)

  return (
    <div className="space-y-6">
      {tailorAsk && (
        <TailorConfirmDialog
          opts={{ ...tailorAsk, profile }}
          onClose={() => setTailorAsk(null)}
          onConfirm={() => runBulkTailor(tailorAsk, { confirm: true })}
          onRuleBased={() => runBulkTailor(tailorAsk, { noLlm: true })}
        />
      )}
      <HeaderPortal>
        <Tabs tabs={JOB_TABS} active={activeTab} onChange={handleTabChange} compact />
        {activeTab === 'jobs' && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" className="!min-h-0 !py-1.5" onClick={() => { setAddInitial(null); setAddJobOpen(true) }}>
              <Plus className="h-4 w-4" />
              Add job
            </Button>
            {hasJobs && (
              <div className="relative">
                <Button variant="secondary" className="!min-h-0 !py-1.5" title={EXPORT_NOTE} onClick={() => setExportOpen(!exportOpen)}>
                  <MoreHorizontal className="h-4 w-4" />
                  Export
                </Button>
                {exportOpen && (
                  <div className="absolute right-0 z-30 mt-1 w-40 rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-stone-700 dark:bg-stone-900">
                    <button type="button" onClick={handleExportJson} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                      <Download className="h-4 w-4" /> JSON, saved rows
                    </button>
                    <button type="button" onClick={handleExportCsv} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-stone-50 dark:hover:bg-stone-800">
                      <Download className="h-4 w-4" /> CSV, saved rows
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </HeaderPortal>

      <ToastStack>
            {runToast && (
              <Toast
                key={`run-${runToast.kind}-${runToast.text}`}
                kind={runToast.kind}
                autoHideMs={runToast.kind === 'success' ? TOAST_AUTO_HIDE_MS : null}
                onDismiss={() => setRunToast(null)}
              >
                <span>{runToast.text}</span>
              </Toast>
            )}
            {activeTab === 'jobs' && addNote && (
              <Toast key="add-note" onDismiss={() => setAddNote(null)}>
                <span>{addNote.text}</span>
                {addNote.retry && (
                  <Button variant="secondary" className="ml-2 !min-h-0 !py-1 !text-xs" disabled={addNote.busy} onClick={() => handleScoreNow(addNote.jobId, state.jobs.find((j) => j.jobId === addNote.jobId)?.title ?? 'the job')}>
                    {addNote.busy ? 'Scoring…' : 'Score now'}
                  </Button>
                )}
              </Toast>
            )}
            {activeTab === 'jobs' && notices.filter((notice) => !closedNotices.has(notice.text)).map((notice) => (
              <Toast
                key={notice.text}
                kind={notice.kind === 'error' ? 'error' : 'info'}
                autoHideMs={notice.kind === 'error' ? null : TOAST_AUTO_HIDE_MS}
                onDismiss={() => closeNotice(notice.text)}
              >
                <span>{notice.text}</span>
                {notice.retry && <Button variant="secondary" className="ml-2 !min-h-0 !py-1 !text-xs" disabled={serverOn ? serverList.status === 'loading' : allAds.status === 'loading'} onClick={serverOn ? serverList.reload : refetchAllAds}>Try again</Button>}
              </Toast>
            ))}
      </ToastStack>

      {activeTab === 'jobs' && (
        <>
          {addJobOpen && <AddJobDialog initial={addInitial} onClose={() => setAddJobOpen(false)} onSaved={handleJobAdded} />}

          {pipelineApiAvailable && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 dark:border-stone-800 dark:bg-stone-900">
              <Button onClick={handleRerunDiscovery} disabled={rerunning || rescrape.view.active || !pipelineApiAvailable}>
                {scrapeRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {scrapeRunning ? `Running…${runningSource ? ` ${runningSource}` : ''}` : 'Re-scrape jobs'}
              </Button>
              <Button variant="secondary" onClick={handleRescore} disabled={rerunning || rescrape.view.active}>
                {scoreRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {scoreRunning ? 'Running… scoring' : 'Re-score'}
              </Button>
              <label className="flex items-center gap-1.5 text-xs text-stone-600 dark:text-stone-400" title="Skips LinkedIn (JobSpy) for this run only; the switch in Settings > Sources stays as it is.">
                <input
                  type="checkbox"
                  checked={skipJobspyOnce}
                  disabled={rerunning || rescrape.view.active}
                  onChange={(e) => setSkipJobspyOnce(e.target.checked)}
                  className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
                />
                Skip LinkedIn this time
              </label>
              <RescrapeProgress view={rescrape.view} />
            </div>
          )}

          {!hasJobs ? (
            <JobEmptyState />
          ) : (
            <div className="space-y-6 animate-fade-in">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-stone-600 dark:text-stone-400">
                <span>{serverShown ? `${serverList.total} of ${serverList.counts?.baseTotal ?? serverList.total}` : `${filteredJobs.length} of ${baseRows.length}`} jobs shown</span>
                {autoLoadNote && <span className="text-xs text-teal-700 dark:text-teal-300">{autoLoadNote}</span>}
              </p>

              {routeEnabled && (
                <JobListControls
                  mode={listMode}
                  onMode={setListMode}
                  options={serverShown ? serverList.counts?.classOptions ?? [] : (listMode === 'all' && composedRows ? classOptions(composedRows) : [])}
                  classes={listClasses}
                  onClasses={setListClasses}
                  recent={seenRecentlyOnly}
                  onRecent={setSeenRecentlyOnly}
                  windowDays={serverShown ? serverList.activeWindowDays : activeWindowDays}
                />
              )}

              <JobFilters filters={filtersShown} searchNote={useComposed && listMode === 'all' ? ALL_SEARCH_NOTE : null} offListDisabledNote={useComposed ? OFF_LIST_NOTE : null} sites={sites} providers={providers} jobs={baseRows} facets={facets} applicationStore={applicationStore} basicProfile={profile?.basicProfile} onChange={handleFilterChange} />
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
              {statusError && <Alert variant="error">{statusError}</Alert>}
              {pending > 0 && <Alert variant="info">{PENDING_NOTICE(pending)}</Alert>}
              <JobTable
                jobs={filteredJobs}
                onStatusChange={handleStatusChange}
                onApply={setApplyJob}
                apiAvailable={pipelineApiAvailable}
                onJobUpdated={handleJobUpdated}
                selectedJobIds={selectedJobIds}
                classView={useComposed}
                reference={reference}
                onAddFromRow={handleAddFromRow}
                onToggleSelect={handleToggleSelect}
                onToggleSelectAll={handleToggleSelectAll}
                onJobSelect={setSelectedJob}
                server={serverShown ? {
                  loading: serverList.status === 'loading',
                  total: serverList.total,
                  pageSize: serverList.limit ?? serverList.rows.length,
                  loadingMore: serverList.loadingMore,
                  sort: tableSort,
                  onSort: onTableSort,
                  onShowMore: serverList.more,
                  hasScores: Boolean(facets?.hasScores),
                  hasProvider: (facets?.providers?.length ?? 0) > 0,
                } : null}
              />
            </div>
          )}
        </>
      )}

      {activeTab === 'pipeline' && (
        <div className="space-y-6">
          <PipelineHealthPanel health={health} pipelineState={pipelineState} />
          <PipelineOrchestrator state={state} onImport={handleImport} onHealthChange={handleHealthChange} onRefresh={serverOn ? handleRefreshFromRun : null} />
          <JobImportPanel state={state} onImport={handleImport} />
          {pipelineApiAvailable && <JobUrlImport onImported={handleUrlImported} />}
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

      {activeTab === 'activity' && (
        <div className="space-y-6">
          <Card title="Latest Re-scrape" description="Every event of the most recent Re-scrape. Older runs are in the history below.">
            <RescrapeEventLog view={rescrape.view} />
          </Card>
          <ActivityScreen />
        </div>
      )}

      {applyJob && <QuickApplyDialog job={stripDisplayFields(applyJob)} cache={applications} onClose={() => setApplyJob(null)} />}

      <JobDetailDrawer
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        apiAvailable={pipelineApiAvailable}
      />
    </div>
  )
}
