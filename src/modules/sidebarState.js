/** Whether the desktop sidebar is collapsed to icons, remembered across page loads. */
export const SIDEBAR_COLLAPSED_KEY = 'job-dashboard-sidebar-collapsed'

function defaultStorage() {
  try { return globalThis.localStorage ?? null } catch { return null }
}

/** Collapsed only when the stored value says so; no storage or an unreadable value is expanded. */
export function loadSidebarCollapsed(storage = defaultStorage()) {
  try { return storage?.getItem(SIDEBAR_COLLAPSED_KEY) === 'true' } catch { return false }
}

export function saveSidebarCollapsed(collapsed, storage = defaultStorage()) {
  try { storage?.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? 'true' : 'false') } catch { /* private mode: the choice lasts for this page only */ }
}
