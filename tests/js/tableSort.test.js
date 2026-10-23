import { describe, it, expect } from 'vitest'
import { nextSort, sortRows } from '../../src/modules/tableSort.js'
import { PRIORITIES } from '../../src/modules/jobs/matchScore.js'

const columns = {
  score: { type: 'number', value: (r) => r.score },
  name: { type: 'text', value: (r) => r.name },
  when: { type: 'date', value: (r) => r.when },
  priority: { type: 'rank', order: PRIORITIES, value: (r) => r.priority },
}
const ids = (rows) => rows.map((r) => r.id)

describe('sortRows', () => {
  const rows = [
    { id: 'a', score: 40, name: 'beta' },
    { id: 'b', score: 90, name: 'Alpha' },
    { id: 'c', score: null, name: 'gamma' },
    { id: 'd', score: 90, name: '' },
  ]

  it('sorts numbers both ways, with ties in input order', () => {
    expect(ids(sortRows(rows, { key: 'score', dir: 'desc' }, columns))).toEqual(['b', 'd', 'a', 'c'])
    expect(ids(sortRows(rows, { key: 'score', dir: 'asc' }, columns))).toEqual(['a', 'b', 'd', 'c'])
  })

  it('keeps empty values last in either direction', () => {
    expect(ids(sortRows(rows, { key: 'name', dir: 'asc' }, columns))).toEqual(['b', 'a', 'c', 'd'])
    expect(ids(sortRows(rows, { key: 'name', dir: 'desc' }, columns))).toEqual(['c', 'a', 'b', 'd'])
  })

  it('compares text without regard to case', () => {
    const r = [{ id: 'x', name: 'banana' }, { id: 'y', name: 'Apple' }]
    expect(ids(sortRows(r, { key: 'name', dir: 'asc' }, columns))).toEqual(['y', 'x'])
  })

  it('ignores surrounding whitespace in text', () => {
    const r = [{ id: 'x', name: 'Beta' }, { id: 'y', name: ' Gamma' }, { id: 'z', name: 'Alpha ' }]
    expect(ids(sortRows(r, { key: 'name', dir: 'asc' }, columns))).toEqual(['z', 'x', 'y'])
  })

  it('orders ranks by their list, unknown values after the known ones', () => {
    const r = ['P3', 'Reject', 'P1', 'other', 'P2'].map((priority) => ({ id: priority, priority }))
    expect(ids(sortRows(r, { key: 'priority', dir: 'asc' }, columns))).toEqual(['P1', 'P2', 'P3', 'Reject', 'other'])
  })

  it('sorts ISO dates newest first when descending', () => {
    const r = [{ id: 'old', when: '2026-01-02' }, { id: 'new', when: '2026-09-01' }, { id: 'none' }]
    expect(ids(sortRows(r, { key: 'when', dir: 'desc' }, columns))).toEqual(['new', 'old', 'none'])
  })

  it('does not mutate its input and ignores an unknown column', () => {
    const copy = [...rows]
    sortRows(rows, { key: 'score', dir: 'asc' }, columns)
    expect(rows).toEqual(copy)
    expect(sortRows(rows, { key: 'nope', dir: 'asc' }, columns)).toBe(rows)
  })
})

describe('nextSort', () => {
  it('starts numbers and dates descending, text and ranks ascending', () => {
    expect(nextSort(null, 'score', columns)).toEqual({ key: 'score', dir: 'desc' })
    expect(nextSort(null, 'when', columns)).toEqual({ key: 'when', dir: 'desc' })
    expect(nextSort(null, 'name', columns)).toEqual({ key: 'name', dir: 'asc' })
    expect(nextSort(null, 'priority', columns)).toEqual({ key: 'priority', dir: 'asc' })
  })

  it('reverses on a second click and restarts on a different column', () => {
    const s1 = nextSort({ key: 'score', dir: 'desc' }, 'score', columns)
    expect(s1).toEqual({ key: 'score', dir: 'asc' })
    expect(nextSort(s1, 'score', columns)).toEqual({ key: 'score', dir: 'desc' })
    expect(nextSort(s1, 'name', columns)).toEqual({ key: 'name', dir: 'asc' })
  })
})
