import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

/** A dropdown with a checkbox per option; the closed state lists what is selected. */
export default function MultiSelectDropdown({ label, selected = [], onChange, options = [], placeholder = 'All' }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!root.current?.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (opt) => {
    onChange(selected.includes(opt) ? selected.filter((s) => s !== opt) : options.filter((o) => o === opt || selected.includes(o)))
  }
  const summary = selected.length === 0 ? placeholder : selected.length <= 3 ? selected.join(', ') : `${selected.length} selected`

  return (
    <div ref={root} className="relative">
      {label && <span className="mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300">{label}</span>}
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg border border-stone-300 px-3 py-2.5 text-left text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
      >
        <span className="truncate">{summary}</span>
        <ChevronDown className="ml-2 h-4 w-4 shrink-0 text-stone-500" />
      </button>
      {open && (
        <div role="listbox" aria-multiselectable="true" className="absolute z-20 mt-1 w-full rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-700 dark:bg-stone-950">
          {options.map((opt) => (
            <label key={opt} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-stone-100 dark:hover:bg-stone-800">
              <input
                type="checkbox"
                checked={selected.includes(opt)}
                onChange={() => toggle(opt)}
                className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
              />
              {opt}
            </label>
          ))}
          {selected.length > 0 && (
            <button type="button" onClick={() => onChange([])} className="mt-1 w-full rounded-md px-2 py-1.5 text-left text-xs text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800">
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  )
}
