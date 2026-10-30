/**
 * The Settings map (docs/redesign/SETTINGS_PLAN.md, sections 2 and 5). One source for the left navigation, the search
 * box and `openSettings(sectionId)`. Pure data: no React, no storage. SettingsHome supplies what each section renders,
 * keyed by section id, and tests/js/settingsRegistry.test.js checks that every id has one.
 *
 * A new setting adds a section here under the category where the owner would look for it. It never adds a top-level
 * screen. `risky` marks a section that can raise spend, send data out or delete; search only opens such a section,
 * it never renders its control.
 */

export const SETTINGS_CATEGORIES = [
  { id: 'job-search', title: 'Job search', empty: null },
  { id: 'sources', title: 'Sources', empty: null },
  { id: 'applications', title: 'Applications', empty: null },
  { id: 'ai-costs', title: 'AI & costs', empty: null },
  { id: 'privacy-security', title: 'Privacy & security', empty: null },
  { id: 'data-backups', title: 'Data & backups', empty: null },
  { id: 'general', title: 'General', empty: null },
  { id: 'danger-zone', title: 'Danger zone', empty: null },
]

export const SETTINGS_SECTIONS = [
  { id: 'scoring-weights', category: 'job-search', title: 'Scoring weights', keywords: ['weights', 'scoring', 'score', 're-score', 'sliders'] },
  { id: 'job-boards', category: 'sources', title: 'Job boards', keywords: ['sources', 'boards', 'providers', 'joberty', 'opt-in', 'scrape', 'discovery', 'terms'] },
  { id: 'application-tracking', category: 'applications', title: 'Tracking and board columns', keywords: ['tracking', 'tracker', 'board', 'columns', 'stages', 'applications'] },
  { id: 'application-notifications', category: 'applications', title: 'Notifications', keywords: ['notifications', 'reminders', 'follow-up', 'nudges'], note: 'Follow-up reminders are not configurable yet.' },
  { id: 'application-migration', category: 'applications', title: 'Application tracking migration', keywords: ['migration', 'migrate', 'import', 'tracking', 'old format'] },
  { id: 'ai-budget', category: 'ai-costs', title: 'AI budget, provider and usage', risky: 'spend', keywords: ['ai', 'budget', 'limit', 'cost', 'automation', 'provider', 'model', 'prices', 'pricing', 'feature', 'toggles', 'usage', 'ledger', 'cache', 'temperature', 'tokens', 'gate'] },
  { id: 'secrets', category: 'privacy-security', title: 'Secrets and keys', risky: 'egress', keywords: ['secrets', 'keys', 'api key', 'linkedin', 'li_at', 'cookie', 'privacy', 'security'] },
  { id: 'backup-restore', category: 'data-backups', title: 'Backup / restore', risky: 'delete', keywords: ['backup', 'restore', 'zip', 'import', 'export', 'jobs json'] },
  { id: 'demo-data', category: 'data-backups', title: 'Try with demo data', keywords: ['demo', 'sample', 'fictional'] },
  { id: 'data-paths', category: 'data-backups', title: 'Data paths', keywords: ['paths', 'files', 'data', 'locations', 'folders'] },
  { id: 'pipeline-status', category: 'general', title: 'Pipeline API status', keywords: ['pipeline', 'api', 'status', 'health', 'offline'] },
  { id: 'cli-commands', category: 'general', title: 'Advanced — CLI commands', keywords: ['cli', 'commands', 'terminal', 'discover', 'score', 'tailor', 'advanced'] },
  { id: 'clear-local-data', category: 'danger-zone', title: 'Clear local data', risky: 'delete', keywords: ['clear', 'reset', 'delete', 'wipe', 'local data'] },
]

export const DEFAULT_SETTINGS_CATEGORY = SETTINGS_CATEGORIES[0].id

export function isCategoryId(id) {
  return SETTINGS_CATEGORIES.some((c) => c.id === id)
}

export function findSection(sectionId) {
  return SETTINGS_SECTIONS.find((s) => s.id === sectionId) ?? null
}

export function sectionsOf(categoryId) {
  return SETTINGS_SECTIONS.filter((s) => s.category === categoryId)
}

/** Sections whose title, keywords or category title contain every word of the query (case-insensitive). Empty query: none. */
export function searchSettings(query) {
  const words = String(query ?? '').toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return []
  return SETTINGS_SECTIONS.filter((section) => {
    const category = SETTINGS_CATEGORIES.find((c) => c.id === section.category)
    const haystack = [section.title, category?.title, ...section.keywords].join(' ').toLowerCase()
    return words.every((w) => haystack.includes(w))
  })
}
