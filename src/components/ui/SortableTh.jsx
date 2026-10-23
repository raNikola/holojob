import { useCallback, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { nextSort } from '../../modules/tableSort'

/** Sort state for one table: `initial` is `{ key, dir }`, `columns` the table's column map. */
export function useTableSort(initial, columns) {
  const [sort, setSort] = useState(initial)
  const toggle = useCallback((key) => setSort((s) => nextSort(s, key, columns)), [columns])
  return [sort, toggle]
}

export default function SortableTh({ label, sortKey, sort, onSort, className = '' }) {
  const active = sort?.key === sortKey
  const Icon = !active ? ChevronsUpDown : sort.dir === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={className} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 uppercase tracking-wide hover:text-stone-900 dark:hover:text-stone-100 ${active ? 'text-stone-900 dark:text-stone-100' : ''}`}
      >
        {label}
        <Icon className={`h-3 w-3 ${active ? '' : 'opacity-40'}`} aria-hidden="true" />
      </button>
    </th>
  )
}
