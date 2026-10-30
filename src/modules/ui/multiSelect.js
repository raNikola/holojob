/** Selection logic of the multi-select dropdown (components/ui/MultiSelectDropdown.jsx). Pure. */

/** Options as `{ value, label }`; a plain string is its own label. */
export function normalizeOptions(options) {
  return (options || []).map((o) => (typeof o === 'string' ? { value: o, label: o } : { value: o.value, label: o.label ?? o.value }))
}

const same = (a, b) => String(a).toLowerCase() === String(b).toLowerCase()

export function isSelected(selected, value) {
  return selected.some((s) => same(s, value))
}

/**
 * Adds or removes `value`. Every other selected value stays, also one the current options do not
 * list (a saved value whose job is gone, or one saved in another case), so a toggle never drops it silently.
 */
export function toggleValue(selected, value) {
  return isSelected(selected, value) ? selected.filter((s) => !same(s, value)) : [...selected, value]
}

/** Options whose label or value contains `query` (case-insensitive). An empty query keeps all. */
export function filterOptions(options, query) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return options
  return options.filter((o) => `${o.label} ${o.value}`.toLowerCase().includes(q))
}

/** Closed-button text: the placeholder for nothing selected, the name for one, else "3 selected". */
export function summaryLabel(selected, placeholder = 'All') {
  if (selected.length === 0) return placeholder
  if (selected.length === 1) return selected[0]
  return `${selected.length} selected`
}

/** Next focus index in a list of `length` rows for an arrow / Home / End key; the list does not wrap. -1 = none focused yet. */
export function nextIndex(current, key, length) {
  if (length <= 0) return -1
  if (key === 'Home') return 0
  if (key === 'End') return length - 1
  if (key === 'ArrowDown') return current < 0 ? 0 : Math.min(current + 1, length - 1)
  if (key === 'ArrowUp') return current < 0 ? length - 1 : Math.max(current - 1, 0)
  return current
}

/** The rows to show: the options, then any selected value the options do not list, so it can still be unticked. */
export function withSelectedExtras(options, selected) {
  const extras = selected.filter((s) => !options.some((o) => same(o.value, s))).map((value) => ({ value, label: value }))
  return [...options, ...extras]
}
