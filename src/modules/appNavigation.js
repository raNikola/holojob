import { DEFAULT_SETTINGS_CATEGORY, findSection, isCategoryId } from './settings/settingsRegistry'

export const VIEWS = {
  ONBOARDING: 'onboarding',
  DASHBOARD: 'dashboard',
  PROFILE: 'profile',
  PROFILE_EDIT: 'profile-edit',
  INTELLIGENCE: 'intelligence',
  JOBS: 'jobs',
  APPLICATIONS: 'applications',
  RESUMES: 'resumes',
  CVS: 'my-cvs',
  SETTINGS: 'settings',
  CAREER_STRATEGY: 'career-strategy',
  AI_COMMAND: 'ai-command',
  OUTREACH: 'outreach',
  QUALITY: 'quality',
}

export const VIEW_STORAGE_KEY = 'job-dashboard-active-view'
export const JOBS_TAB_STORAGE_KEY = 'job-dashboard-jobs-tab'
export const SETTINGS_CATEGORY_STORAGE_KEY = 'job-dashboard-settings-category'
export const OPEN_SETTINGS_EVENT = 'holojob:open-settings'
export const OPEN_QUESTIONNAIRE_EVENT = 'holojob:open-questionnaire'
export const OPEN_ONBOARDING_EVENT = 'holojob:open-onboarding'

const SHELL_VIEWS = new Set([
  VIEWS.DASHBOARD,
  VIEWS.PROFILE,
  VIEWS.PROFILE_EDIT,
  VIEWS.INTELLIGENCE,
  VIEWS.JOBS,
  VIEWS.APPLICATIONS,
  VIEWS.RESUMES,
  VIEWS.CVS,
  VIEWS.SETTINGS,
  VIEWS.CAREER_STRATEGY,
  VIEWS.AI_COMMAND,
  VIEWS.OUTREACH,
  VIEWS.QUALITY,
])

const LEGACY_VIEWS = new Set(['intelligence', 'jobs'])

export function isOnboardingComplete(profile) {
  return Boolean(profile?.meta?.onboardingComplete)
}

export function isValidView(view) {
  return view === VIEWS.ONBOARDING || SHELL_VIEWS.has(view)
}

export function isShellView(view) {
  return SHELL_VIEWS.has(view)
}

export function loadInitialView(profile) {
  if (!isOnboardingComplete(profile)) {
    return VIEWS.ONBOARDING
  }

  try {
    const saved = sessionStorage.getItem(VIEW_STORAGE_KEY)
    if (saved === VIEWS.ONBOARDING) {
      return VIEWS.DASHBOARD
    }
    if (saved && isValidView(saved) && isShellView(saved)) {
      return saved
    }
    if (saved && LEGACY_VIEWS.has(saved)) {
      return saved === 'jobs' ? VIEWS.JOBS : VIEWS.INTELLIGENCE
    }
  } catch {
    /* ignore */
  }

  return VIEWS.DASHBOARD
}

export function loadDemoInitialView(profile, demoMode) {
  if (demoMode && isOnboardingComplete(profile)) {
    return VIEWS.JOBS
  }
  return loadInitialView(profile)
}

export function persistView(view) {
  try {
    if (isValidView(view) && view !== VIEWS.ONBOARDING) {
      sessionStorage.setItem(VIEW_STORAGE_KEY, view)
    }
  } catch {
    /* ignore */
  }
}

export function persistJobsTab(tab) {
  try {
    sessionStorage.setItem(JOBS_TAB_STORAGE_KEY, tab)
  } catch {
    /* ignore */
  }
}

export function loadJobsTab() {
  try {
    const saved = sessionStorage.getItem(JOBS_TAB_STORAGE_KEY)
    if (saved === 'jobs' || saved === 'pipeline' || saved === 'analytics') {
      return saved
    }
  } catch {
    /* ignore */
  }
  return 'jobs'
}

export function persistSettingsCategory(categoryId) {
  try {
    if (isCategoryId(categoryId)) sessionStorage.setItem(SETTINGS_CATEGORY_STORAGE_KEY, categoryId)
  } catch {
    /* ignore */
  }
}

export function loadSettingsCategory() {
  try {
    const saved = sessionStorage.getItem(SETTINGS_CATEGORY_STORAGE_KEY)
    if (isCategoryId(saved)) return saved
  } catch {
    /* ignore */
  }
  return DEFAULT_SETTINGS_CATEGORY
}

let pendingSettingsSection = null

/** The section `openSettings` asked for, once: SettingsHome calls it on mount and when the event reaches it. */
export function takePendingSettingsSection() {
  const id = pendingSettingsSection
  pendingSettingsSection = null
  return id
}

/** Opens Settings on the category of `sectionId` and scrolls to it. App switches the view; SettingsHome selects and scrolls. */
export function openSettings(sectionId) {
  const section = findSection(sectionId)
  if (section) {
    persistSettingsCategory(section.category)
    pendingSettingsSection = section.id
  }
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(OPEN_SETTINGS_EVENT, { detail: { sectionId } }))
}

/** Opens the profile editor on the questionnaire step; App listens. */
export function openQuestionnaire() {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(OPEN_QUESTIONNAIRE_EVENT))
}

/** Goes to the start of onboarding (after a profile reset); App listens. */
export function openOnboarding() {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(OPEN_ONBOARDING_EVENT))
}

export const NAV_ITEMS = [
  { id: VIEWS.DASHBOARD, label: 'Dashboard', icon: 'LayoutDashboard' },
  { id: VIEWS.PROFILE, label: 'Profile', icon: 'User' },
  { id: VIEWS.INTELLIGENCE, label: 'Intelligence', icon: 'Brain' },
  { id: VIEWS.JOBS, label: 'Jobs', icon: 'Briefcase' },
  { id: VIEWS.APPLICATIONS, label: 'Applications', icon: 'ClipboardList' },
  { id: VIEWS.RESUMES, label: 'Resumes', icon: 'FileText' },
  { id: VIEWS.CVS, label: 'My CVs', icon: 'FileUser' },
  { id: VIEWS.CAREER_STRATEGY, label: 'Career Strategy', icon: 'Target' },
  { id: VIEWS.AI_COMMAND, label: 'AI Copilot', icon: 'MessageSquare' },
  { id: VIEWS.OUTREACH, label: 'Outreach', icon: 'Users' },
  { id: VIEWS.QUALITY, label: 'Quality Audit', icon: 'ShieldCheck' },
  { id: VIEWS.SETTINGS, label: 'Settings', icon: 'Settings' },
]

export const MOBILE_NAV_ITEMS = [
  { id: VIEWS.DASHBOARD, label: 'Home', icon: 'LayoutDashboard' },
  { id: VIEWS.JOBS, label: 'Jobs', icon: 'Briefcase' },
  { id: VIEWS.APPLICATIONS, label: 'Apps', icon: 'ClipboardList' },
  { id: VIEWS.RESUMES, label: 'Resumes', icon: 'FileText' },
  { id: VIEWS.PROFILE, label: 'Profile', icon: 'User' },
]

export const VIEW_TITLES = {
  [VIEWS.DASHBOARD]: 'Dashboard',
  [VIEWS.PROFILE]: 'Profile',
  [VIEWS.PROFILE_EDIT]: 'Edit Profile',
  [VIEWS.INTELLIGENCE]: 'Intelligence',
  [VIEWS.JOBS]: 'Jobs',
  [VIEWS.APPLICATIONS]: 'Applications',
  [VIEWS.RESUMES]: 'Resumes',
  [VIEWS.CVS]: 'My CVs',
  [VIEWS.SETTINGS]: 'Settings',
  [VIEWS.CAREER_STRATEGY]: 'Career Strategy',
  [VIEWS.AI_COMMAND]: 'AI Copilot',
  [VIEWS.OUTREACH]: 'Outreach',
  [VIEWS.QUALITY]: 'Quality Audit',
}
