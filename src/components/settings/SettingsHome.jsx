import { useCallback, useEffect, useState } from 'react'
import { Copy, Download, Loader2, Search, Trash2, Upload } from 'lucide-react'
import Card from '../ui/Card'
import AISettingsPanel from '../ai/AISettingsPanel'
import SecretsPanel from './SecretsPanel'
import JobBoardsPanel from './JobBoardsPanel'
import CompleteProfilePanel from './CompleteProfilePanel'
import ResetProfilePanel from './ResetProfilePanel'
import ScoringWeightsPanel from './ScoringWeightsPanel'
import ApplicationMigrationPanel from './ApplicationMigrationPanel'
import ApplicationSettingsPanel from './ApplicationSettingsPanel'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { useProfile } from '../../context/ProfileContext'
import { clearIntelligence, saveIntelligence } from '../../modules/intelligence/intelligenceExport'
import { JOBS_STORAGE_KEY, importJobsFromFile, loadJobs, saveJobs } from '../../modules/jobs/jobStorage'
import {
  buildDiscoveryCommand,
  buildScoringCommand,
  buildTailorCommand,
  copyToClipboard,
  probePipelineApi,
} from '../../modules/jobs/pipelineRunner'
import { loadDemoData } from '../../modules/demo/loadDemoData'
import { downloadBackupZip, importBackupZip } from '../../modules/backup/backupClient'
import {
  OPEN_SETTINGS_EVENT, loadSettingsCategory, persistSettingsCategory, takePendingSettingsSection,
} from '../../modules/appNavigation'
import { SETTINGS_CATEGORIES, findSection, searchSettings, sectionsOf } from '../../modules/settings/settingsRegistry'

const FIELD_CLASS = 'w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-100'

export default function SettingsHome() {
  const { profile, resetProfile, updateProfile } = useProfile()
  const [apiProbe, setApiProbe] = useState(null)
  const [copied, setCopied] = useState(null)
  const [importError, setImportError] = useState(null)
  const [status, setStatus] = useState(null)
  const [demoLoading, setDemoLoading] = useState(false)
  const [backupLoading, setBackupLoading] = useState(false)
  const [category, setCategory] = useState(loadSettingsCategory)
  const [query, setQuery] = useState('')
  const [focusSection, setFocusSection] = useState(null)

  useEffect(() => {
    probePipelineApi().then(setApiProbe)
  }, [])

  const goTo = useCallback((sectionId) => {
    const section = findSection(sectionId)
    if (!section) return
    setCategory(section.category)
    persistSettingsCategory(section.category)
    setFocusSection({ id: section.id, at: Date.now() })
  }, [])

  useEffect(() => {
    const take = () => {
      const id = takePendingSettingsSection()
      if (id) goTo(id)
    }
    take()
    window.addEventListener(OPEN_SETTINGS_EVENT, take)
    return () => window.removeEventListener(OPEN_SETTINGS_EVENT, take)
  }, [goTo])

  useEffect(() => {
    if (!focusSection) return
    document.querySelector(`[data-settings-section="${focusSection.id}"]`)?.scrollIntoView({ block: 'start' })
  }, [focusSection])

  const selectCategory = (id) => {
    setCategory(id)
    persistSettingsCategory(id)
  }

  const handleCopy = async (text, key) => {
    await copyToClipboard(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  const handleExportBackup = async () => {
    setBackupLoading(true)
    setImportError(null)
    try {
      const name = await downloadBackupZip(profile)
      setStatus(`Downloaded ${name}`)
    } catch (e) {
      setImportError(e.message)
    } finally {
      setBackupLoading(false)
    }
  }

  const handleImportBackup = async (file) => {
    if (!file) return
    if (!window.confirm('Restore from backup? This overwrites data/ files on disk.')) return
    setBackupLoading(true)
    setImportError(null)
    try {
      const result = await importBackupZip(file)
      setStatus(`Restored ${result.count} files from backup. Reload the page to sync browser state.`)
      const intelRes = await fetch('/api/intelligence/candidate')
      if (intelRes.ok) {
        const intel = await intelRes.json()
        if (intel) saveIntelligence(intel)
      }
    } catch (e) {
      setImportError(e.message)
    } finally {
      setBackupLoading(false)
    }
  }

  const handleImportJobs = async (file) => {
    if (!file) return
    setImportError(null)
    try {
      const json = JSON.parse(await file.text())
      const next = importJobsFromFile(json, loadJobs())
      saveJobs(next)
      setStatus(`Imported ${next.jobs.length} jobs.`)
    } catch (e) {
      setImportError(e.message)
    }
  }

  const handleLoadDemo = async () => {
    setDemoLoading(true)
    setImportError(null)
    try {
      const result = await loadDemoData({ updateProfile })
      setStatus(`Loaded demo data: ${result.profile.basicProfile?.fullName}, ${result.jobCount} scored jobs.`)
    } catch (e) {
      setImportError(e.message)
    } finally {
      setDemoLoading(false)
    }
  }

  const handleClearAll = () => {
    if (!window.confirm('Clear all local data (profile, intelligence, jobs)? This cannot be undone.')) return
    resetProfile()
    clearIntelligence()
    localStorage.removeItem(JOBS_STORAGE_KEY)
    setStatus('All local data cleared. Reload to start fresh.')
  }

  const ctx = {
    apiProbe, copied, importError, status, demoLoading, backupLoading,
    handleCopy, handleExportBackup, handleImportBackup, handleImportJobs, handleLoadDemo, handleClearAll,
    discoverCmd: buildDiscoveryCommand({ providers: 'serbia' }),
    scoreCmd: buildScoringCommand(),
    tailorCmd: buildTailorCommand({ priority: 'P1', limit: 5 }),
  }
  const results = searchSettings(query)

  // Every category stays mounted and is hidden with CSS, so a draft typed in one panel survives switching.
  return (
    <div className="space-y-4">
      {status && <p className="text-xs text-teal-700 dark:text-teal-300">{status}</p>}

      <div className="relative max-w-2xl">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-stone-400" />
        <input
          type="search"
          aria-label="Search settings"
          placeholder="Search settings"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className={`${FIELD_CLASS} pl-9`}
        />
        {query.trim() && (
          <ul className="mt-2 space-y-1 rounded-lg border border-stone-200 bg-white p-2 text-sm dark:border-stone-800 dark:bg-stone-900">
            {results.length === 0 && <li className="px-2 py-1 text-stone-500">No settings match.</li>}
            {results.map((section) => (
              <li key={section.id}>
                <button
                  type="button"
                  onClick={() => { goTo(section.id); setQuery('') }}
                  className="w-full rounded px-2 py-1 text-left hover:bg-stone-100 dark:hover:bg-stone-800"
                >
                  {section.title}
                  <span className="ml-2 text-xs text-stone-500">{SETTINGS_CATEGORIES.find((c) => c.id === section.category)?.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-4 md:flex-row md:items-start">
        <select
          aria-label="Settings category"
          value={category}
          onChange={(e) => selectCategory(e.target.value)}
          className={`${FIELD_CLASS} md:hidden`}
        >
          {SETTINGS_CATEGORIES.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
        <nav aria-label="Settings categories" className="hidden w-52 shrink-0 space-y-1 md:block">
          {SETTINGS_CATEGORIES.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => selectCategory(c.id)}
              aria-current={c.id === category ? 'page' : undefined}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm ${c.id === category
                ? 'bg-teal-50 font-medium text-teal-800 dark:bg-teal-950/40 dark:text-teal-200'
                : 'text-stone-700 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800'}`}
            >
              {c.title}
            </button>
          ))}
        </nav>

        <div className="min-w-0 flex-1">
          {SETTINGS_CATEGORIES.map((c) => {
            const sections = sectionsOf(c.id)
            return (
              <div key={c.id} data-settings-category={c.id} className={c.id === category ? 'max-w-4xl space-y-6' : 'hidden'}>
                <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">{c.title}</h2>
                {sections.length === 0 && c.empty && <p className="text-sm text-stone-600 dark:text-stone-400">{c.empty}</p>}
                {sections.map((section) => (
                  <section key={section.id} data-settings-section={section.id} className="scroll-mt-4">
                    {RENDERERS[section.id](ctx)}
                  </section>
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// What each registered section shows (the registry holds the map, this holds the panels). Keyed by section id;
// tests/js/settingsRegistry.test.js fails when an id has no entry here or an entry has no id.
const RENDERERS = {
  'scoring-weights': () => <ScoringWeightsPanel />,
  'job-boards': () => <JobBoardsPanel />,
  'application-tracking': () => <ApplicationSettingsPanel />,
  'application-notifications': () => (
    <Card title="Notifications">
      <p className="text-sm text-stone-600 dark:text-stone-400">{findSection('application-notifications').note}</p>
    </Card>
  ),
  'application-migration': () => <ApplicationMigrationPanel />,
  'ai-budget': () => <AISettingsPanel />,
  'secrets': () => <SecretsPanel />,
  'complete-profile': () => <CompleteProfilePanel />,
  'backup-restore': (c) => (
    <Card title="Backup / restore">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Download a single ZIP with profile, intelligence, jobs, resumes, and outreach data.
      </p>
      <div className="flex flex-col gap-3">
        <Button variant="secondary" onClick={c.handleExportBackup} disabled={c.backupLoading}>
          {c.backupLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Download backup ZIP
        </Button>
        <div>
          <input
            id="settings-import-backup"
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => c.handleImportBackup(e.target.files?.[0])}
          />
          <Button variant="secondary" onClick={() => document.getElementById('settings-import-backup')?.click()} disabled={c.backupLoading}>
            <Upload className="h-4 w-4" />
            Restore from backup ZIP
          </Button>
        </div>
        <div>
          <input
            id="settings-import-jobs"
            type="file"
            accept=".json"
            className="hidden"
            onChange={(e) => c.handleImportJobs(e.target.files?.[0])}
          />
          <Button variant="ghost" onClick={() => document.getElementById('settings-import-jobs')?.click()}>
            <Upload className="h-4 w-4" />
            Import jobs JSON only
          </Button>
        </div>
        {c.importError && <Alert variant="error" title="Import failed">{c.importError}</Alert>}
      </div>
    </Card>
  ),
  'demo-data': (c) => (
    <Card title="Try with demo data">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Load a fictional candidate profile, intelligence, and scored jobs to explore Career OS without uploading your resume.
      </p>
      <Button variant="secondary" onClick={c.handleLoadDemo} disabled={c.demoLoading}>
        {c.demoLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
        Load demo data
      </Button>
    </Card>
  ),
  'data-paths': () => (
    <Card title="Data paths">
      <dl className="space-y-2 text-sm text-stone-700 dark:text-stone-300">
        <div><dt className="text-xs uppercase text-stone-500">Profile</dt><dd><code>data/profile/candidate-profile.json</code></dd></div>
        <div><dt className="text-xs uppercase text-stone-500">Intelligence</dt><dd><code>data/intelligence/candidate-intelligence.json</code></dd></div>
        <div><dt className="text-xs uppercase text-stone-500">Jobs</dt><dd><code>data/jobs/discovered_jobs.json</code>, <code>scored_jobs.json</code></dd></div>
        <div><dt className="text-xs uppercase text-stone-500">Resumes</dt><dd><code>data/resumes/</code></dd></div>
      </dl>
    </Card>
  ),
  'pipeline-status': (c) => (
    <Card title="Pipeline API status">
      {!c.apiProbe ? (
        <p className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" /> Checking…</p>
      ) : (
        <p className="text-sm text-stone-700 dark:text-stone-300">
          {c.apiProbe.available ? 'Pipeline API is available.' : `Pipeline API offline: ${c.apiProbe.reason || 'unavailable'}`}
        </p>
      )}
    </Card>
  ),
  'cli-commands': (c) => (
    <details className="rounded-xl border border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-900">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-stone-700 dark:text-stone-300">
        Advanced — CLI commands
      </summary>
      <div className="space-y-3 border-t border-stone-200 px-4 py-4 dark:border-stone-800">
        {[['d', c.discoverCmd, 'discover'], ['s', c.scoreCmd, 'score'], ['t', c.tailorCmd, 'tailor']].map(([key, cmd, label]) => (
          <div key={key}>
            <pre className="overflow-x-auto rounded bg-stone-100 p-2 text-xs dark:bg-stone-800">{cmd}</pre>
            <Button variant="secondary" className="mt-1 !text-xs" onClick={() => c.handleCopy(cmd, key)}>
              <Copy className="h-3 w-3" />{c.copied === key ? 'Copied' : `Copy ${label}`}
            </Button>
          </div>
        ))}
      </div>
    </details>
  ),
  'reset-profile': () => <ResetProfilePanel />,
  'clear-local-data': (c) => (
    <Card title="Clear local data">
      <Button variant="ghost" onClick={c.handleClearAll} className="text-red-600 hover:text-red-700">
        <Trash2 className="h-4 w-4" />
        Clear all local data
      </Button>
    </Card>
  ),
}
