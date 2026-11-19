import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'

/** `slotRef` receives the element a screen fills (via HeaderPortal) with its own tabs and actions, between the title and the theme toggle. */
export default function TopBar({ title, actions = null, slotRef = null }) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const toggleDark = () => {
    document.documentElement.classList.toggle('dark')
    setDark(!dark)
  }

  return (
    <header className="sticky top-0 z-20 border-b border-stone-200 bg-white/80 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:px-6">
        <h1 className="font-display text-lg font-semibold text-stone-900 dark:text-stone-50">{title}</h1>
        <div ref={slotRef} className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-2 empty:hidden" />
        <div className="ml-auto flex items-center gap-2">
          {actions}
          <button
            type="button"
            onClick={toggleDark}
            className="rounded-lg p-2 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"
            aria-label="Toggle dark mode"
          >
            {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
        </div>
      </div>
    </header>
  )
}
