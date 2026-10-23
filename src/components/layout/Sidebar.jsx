import {
  Brain,
  Briefcase,
  ClipboardList,
  FileText,
  LayoutDashboard,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldCheck,
  Target,
  User,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { MOBILE_NAV_ITEMS, NAV_ITEMS } from '../../modules/appNavigation'
import { loadSidebarCollapsed, saveSidebarCollapsed } from '../../modules/sidebarState'

const ICONS = {
  LayoutDashboard,
  User,
  Brain,
  Briefcase,
  ClipboardList,
  FileText,
  Settings,
  Target,
  MessageSquare,
  Users,
  ShieldCheck,
}

function NavButton({ item, active, onNavigate, compact = false, collapsed = false }) {
  const Icon = ICONS[item.icon] || LayoutDashboard
  const isActive = active === item.id || (item.id === 'profile' && active === 'profile-edit')

  return (
    <button
      type="button"
      onClick={() => onNavigate(item.id)}
      title={collapsed ? item.label : undefined}
      aria-label={collapsed ? item.label : undefined}
      className={`relative flex w-full items-center rounded-lg py-2.5 text-sm font-medium transition-colors ${
        collapsed ? 'justify-center px-0' : 'gap-3 px-3'
      } ${
        isActive
          ? 'bg-teal-50 text-teal-800 dark:bg-teal-950/50 dark:text-teal-300'
          : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-200'
      } ${compact ? 'flex-col gap-1 px-2 py-2 text-xs' : ''}`}
    >
      <div className="relative flex items-center justify-center">
        <Icon className={compact ? 'h-5 w-5' : 'h-4 w-4 shrink-0'} />
      </div>
      {!collapsed && <span className={compact ? 'truncate' : 'whitespace-nowrap'}>{item.label}</span>}
    </button>
  )
}

export default function Sidebar({ activeView, onNavigate, onOpenMore }) {
  const [collapsed, setCollapsed] = useState(() => loadSidebarCollapsed())
  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    saveSidebarCollapsed(next)
  }
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose

  return (
    <>
      {/* Pinned to the viewport: the page scrolls, the sidebar does not. */}
      <aside
        data-collapsed={collapsed}
        className={`hidden shrink-0 overflow-x-hidden overflow-y-auto border-r border-stone-200 bg-white transition-[width] duration-200 ease-in-out dark:border-stone-800 dark:bg-stone-950 md:sticky md:top-0 md:flex md:h-screen md:flex-col md:self-start ${
          collapsed ? 'w-16' : 'w-56'
        }`}
      >
        <div className={`flex items-center border-b border-stone-200 py-5 dark:border-stone-800 ${collapsed ? 'justify-center px-2' : 'justify-between px-4'}`}>
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate font-display text-sm font-semibold text-stone-900 dark:text-stone-50">Holojob</p>
              <p className="truncate text-xs text-stone-500">Personal dashboard</p>
            </div>
          )}
          <button
            type="button"
            onClick={toggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="rounded-lg p-2 text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-200"
          >
            <ToggleIcon className="h-4 w-4" />
          </button>
        </div>
        <nav className={`flex flex-1 flex-col gap-1 ${collapsed ? 'p-2' : 'p-3'}`}>
          {NAV_ITEMS.map((item) => (
            <NavButton key={item.id} item={item} active={activeView} onNavigate={onNavigate} collapsed={collapsed} />
          ))}
        </nav>
      </aside>

      <nav className="fixed bottom-0 left-0 right-0 z-30 flex border-t border-stone-200 bg-white/95 backdrop-blur dark:border-stone-800 dark:bg-stone-950/95 md:hidden">
        {MOBILE_NAV_ITEMS.map((item) => (
          <div key={item.id} className="flex-1">
            <NavButton item={item} active={activeView} onNavigate={onNavigate} compact />
          </div>
        ))}
        <div className="flex-1">
          <button
            type="button"
            onClick={onOpenMore}
            className="flex w-full flex-col items-center gap-1 rounded-lg px-2 py-2 text-xs font-medium text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"
          >
            <MoreHorizontal className="h-5 w-5" />
            More
          </button>
        </div>
      </nav>
    </>
  )
}
