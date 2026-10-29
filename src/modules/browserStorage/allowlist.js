/**
 * Browser storage keys (BROWSER_STORAGE_POLICY, sections 1.1 and 2.2). Data only: the wrapper that enforces
 * it at run time is step 5. tests/js/browserStorageAllowlist.test.js fails when a source file uses a key or a
 * storage API that is not listed here, so a new key has to be argued for in this file first.
 *
 * ALLOWED: UI state, useless to anyone who copies it.
 * TOLERATED: keys that exist today and leave the browser in the named step; none may be added to this list.
 * Secrets (an API key, li_at) are never allowed: the AI key left in step 2, li_at in step 3.
 */

export const BROWSER_STORAGE_ALLOWLIST = [
  { key: 'job-dashboard-active-view', store: 'session', maxBytes: 64, reason: 'Which screen is open; lost on tab close; no content.' },
  { key: 'job-dashboard-jobs-tab', store: 'session', maxBytes: 64, reason: 'Which jobs tab is open.' },
  { key: 'job-dashboard-settings-category', store: 'session', maxBytes: 32, reason: 'Which Settings category is open; no content.' },
  { key: 'job-dashboard-sidebar-collapsed', store: 'local', maxBytes: 8, reason: 'Layout preference, true or false.' },
  { key: 'job-dashboard-theme', store: 'local', maxBytes: 16, reason: 'Light or dark choice (not persisted yet).' },
  { key: 'career-os-demo-bootstrap-done', store: 'session', maxBytes: 8, reason: 'Demo-mode flag; exists only in demo mode.' },
]

export const TOLERATED_UNTIL_MIGRATED = [
  { key: 'job-dashboard-ai-settings', store: 'local', until: 'step 5', reason: 'Settings left in step 4 and the key in step 2; read once and removed (aiSettings.js), never written. Only a legacy value waiting for its move may remain; the entry goes with the generic scrub.' },
  { key: 'linkedin_li_at', store: 'local', until: 'step 5', reason: 'LinkedIn cookie left in step 3; only a legacy value waiting for the move may remain. It is read and removed (outreach/linkedinCookie.js), never written; the entry goes with the generic scrub.' },
  { key: 'job-dashboard-candidate-profile', store: 'local', until: 'step 5', reason: 'Server becomes the master (Q1).' },
  { key: 'job-dashboard-candidate-intelligence', store: 'local', until: 'step 5', reason: 'Server becomes the master (Q1).' },
  { key: 'job-dashboard-discovered-jobs', store: 'local', until: 'step 5', reason: 'Server becomes the master (Q1).' },
  { key: 'job-dashboard-pipeline-state', store: 'local', until: 'step 5', reason: 'Derived from the server; removed.' },
  { key: 'job-dashboard-ai-chat', store: 'session', until: 'step 5', reason: 'Chat history becomes in-memory only (Q7).' },
  { key: 'job-dashboard-ai-memory', store: 'local', until: 'step 5', reason: 'Moves to the server or is dropped.' },
  { key: 'job-dashboard-ai-cache', store: 'local', until: 'step 5', reason: 'Redundant cache; removed.' },
  { key: 'job-dashboard-ai-usage', store: 'local', until: 'step 5', reason: 'The server ledger is the truth; removed.' },
  { key: 'job-dashboard-outreach-index', store: 'none', until: 'step 5', reason: 'Dead constant, nothing is written; deleted.' },
]

/** Source files that touch a storage API (localStorage, sessionStorage, indexedDB, document.cookie), relative to the repo root. */
export const STORAGE_API_USERS = [
  'src/components/ai/AICommandCenter.jsx',
  'src/components/dashboard/DashboardHome.jsx',
  'src/components/resumes/ResumeLibrary.jsx',
  'src/components/settings/SettingsHome.jsx',
  'src/context/ProfileContext.jsx',
  'src/modules/ai/aiMemory.js',
  'src/modules/ai/aiResponseCache.js',
  'src/modules/ai/aiSettings.js',
  'src/modules/ai/aiUsageTracker.js',
  'src/modules/appNavigation.js',
  'src/modules/demo/loadDemoData.js',
  'src/modules/intelligence/intelligenceExport.js',
  'src/modules/jobs/jobStorage.js',
  'src/modules/jobs/pipelineState.js',
  'src/modules/outreach/linkedinCookie.js',
  'src/modules/sidebarState.js',
  'src/utils/storage.js',
]
