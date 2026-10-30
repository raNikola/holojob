import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { filterOptions, isSelected, nextIndex, normalizeOptions, summaryLabel, toggleValue, withSelectedExtras } from '../../modules/ui/multiSelect'

/**
 * A dropdown with a search box and a checkbox per option; nothing selected means "all". Options are
 * strings or `{ value, label }`. Keys: Arrow Up / Down, Home, End move between the search box and the
 * rows, Space ticks, Escape closes and returns to the button; a click or tap outside closes it.
 */
export default function MultiSelectDropdown({ label, labelExtra, selected = [], onChange, options = [], placeholder = 'All' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const root = useRef(null)
  const button = useRef(null)
  const search = useRef(null)
  const rows = useRef([])
  const buttonId = useId()
  const popupId = useId()

  const rowsAll = useMemo(() => withSelectedExtras(normalizeOptions(options), selected), [options, selected])
  const visible = filterOptions(rowsAll, query)

  const close = (restoreFocus) => {
    setOpen(false)
    setQuery('')
    if (restoreFocus) button.current?.focus()
  }

  useEffect(() => {
    if (!open) return undefined
    search.current?.focus()
    const onOutside = (e) => { if (!root.current?.contains(e.target)) close(false) }
    document.addEventListener('pointerdown', onOutside)
    return () => document.removeEventListener('pointerdown', onOutside)
  }, [open])

  const focusRow = (i) => {
    if (i < 0) search.current?.focus()
    else rows.current[i]?.focus()
  }

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      close(true)
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return
    const inSearch = document.activeElement === search.current
    if (inSearch && (e.key === 'Home' || e.key === 'End')) return
    e.preventDefault()
    const current = inSearch ? -1 : rows.current.indexOf(document.activeElement)
    if (e.key === 'ArrowUp' && current === 0) { focusRow(-1); return }
    focusRow(nextIndex(current, e.key, visible.length))
  }

  return (
    <div
      ref={root}
      className="relative"
      onBlur={(e) => { if (open && e.relatedTarget && !root.current?.contains(e.relatedTarget)) close(false) }}
    >
      {label && (
        <div className="mb-1.5 flex items-center gap-1">
          <label htmlFor={buttonId} className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}</label>
          {labelExtra}
        </div>
      )}
      <button
        ref={button}
        id={buttonId}
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? popupId : undefined}
        onClick={() => (open ? close(false) : setOpen(true))}
        onKeyDown={(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true) } }}
        className="flex w-full items-center justify-between rounded-lg border border-stone-300 px-3 py-2.5 text-left text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
      >
        <span className="truncate">{summaryLabel(selected, placeholder)}</span>
        <ChevronDown className="ml-2 h-4 w-4 shrink-0 text-stone-500" />
      </button>
      {open && (
        <div
          id={popupId}
          role="group"
          aria-label={label ? `${label} options` : 'Options'}
          onKeyDown={onKeyDown}
          className="absolute z-20 mt-1 w-full min-w-[12rem] rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-700 dark:bg-stone-950"
        >
          <input
            ref={search}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label={label ? `Search ${label}` : 'Search options'}
            placeholder="Search…"
            className="mb-1 w-full rounded-md border border-stone-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
          />
          <div className="max-h-60 overflow-y-auto">
            {visible.length === 0 && <p className="px-2 py-1.5 text-xs text-stone-500">No match</p>}
            {visible.map((opt, i) => (
              <label key={opt.value} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-stone-100 dark:hover:bg-stone-800">
                <input
                  ref={(el) => { rows.current[i] = el }}
                  type="checkbox"
                  checked={isSelected(selected, opt.value)}
                  onChange={() => onChange(toggleValue(selected, opt.value))}
                  className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
                />
                {opt.label}
              </label>
            ))}
          </div>
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
