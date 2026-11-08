/**
 * Click-to-sort for table views. A column is `{ value(row), type }`, where type is
 * 'text' (A-Z first), 'number' or 'date' (largest / newest first), or 'rank'
 * (an ordered list, best first, given as `order`). `firstDir` overrides the natural first direction.
 * Empty values always sort last, whichever way the column runs.
 */

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true })

export function firstDirection(column) {
  if (column.firstDir) return column.firstDir
  return column.type === 'number' || column.type === 'date' ? 'desc' : 'asc'
}

/** The sort after a click on `key`: a new column starts in its natural direction, the same one reverses. */
export function nextSort(current, key, columns) {
  if (current?.key === key) return { key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
  return { key, dir: firstDirection(columns[key]) }
}

function isEmpty(v) {
  return v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v))
}

function compare(column, a, b) {
  if (column.type === 'number') return a - b
  if (column.type === 'rank') {
    const rank = (v) => {
      const i = column.order.indexOf(v)
      return i === -1 ? column.order.length : i
    }
    return rank(a) - rank(b)
  }
  return collator.compare(String(a).trim(), String(b).trim())
}

export function sortRows(rows, sort, columns) {
  const column = sort && columns[sort.key]
  if (!column) return rows
  const sign = sort.dir === 'desc' ? -1 : 1
  return rows
    .map((row, index) => ({ row, index, v: column.value(row) }))
    .sort((a, b) => {
      const ea = isEmpty(a.v)
      const eb = isEmpty(b.v)
      if (ea || eb) return ea === eb ? a.index - b.index : ea ? 1 : -1
      return sign * compare(column, a.v, b.v) || a.index - b.index
    })
    .map((x) => x.row)
}
