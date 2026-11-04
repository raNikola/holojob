import { NAV_ITEMS, VIEWS } from './appNavigation'

/**
 * Presentation groups of the desktop sidebar. Only view ids live here; labels and icons stay in NAV_ITEMS.
 * A null title renders no heading; `pinned` puts the group at the bottom of the sidebar.
 */
export const NAV_GROUPS = [
  { id: 'overview', title: null, items: [VIEWS.DASHBOARD] },
  { id: 'work', title: 'Work', items: [VIEWS.JOBS, VIEWS.APPLICATIONS, VIEWS.OUTREACH] },
  { id: 'candidate', title: 'Candidate', items: [VIEWS.PROFILE, VIEWS.INTELLIGENCE, VIEWS.CVS, VIEWS.CAREER_STRATEGY] },
  { id: 'tools', title: 'Tools', items: [VIEWS.RESUMES, VIEWS.AI_COMMAND] },
  { id: 'system', title: 'System', items: [VIEWS.ACTIVITY, VIEWS.QUALITY] },
  { id: 'settings', title: null, items: [VIEWS.SETTINGS], pinned: true },
]

/** The groups with each view id resolved to its NAV_ITEMS entry; an id without an entry is skipped. */
export function resolveNavGroups(groups = NAV_GROUPS, items = NAV_ITEMS) {
  const byId = new Map(items.map((item) => [item.id, item]))
  return groups.map((group) => ({ ...group, items: group.items.map((id) => byId.get(id)).filter(Boolean) }))
}
