import { describe, expect, it } from 'vitest'
import { filterOptions, isSelected, nextIndex, normalizeOptions, summaryLabel, toggleValue, withSelectedExtras } from '../../src/modules/ui/multiSelect.js'

describe('multi-select selection', () => {
  it('toggles a value on and off', () => {
    expect(toggleValue([], 'a')).toEqual(['a'])
    expect(toggleValue(['a', 'b'], 'a')).toEqual(['b'])
  })

  it('keeps a selected value that the options do not list, and unticks one saved in another case', () => {
    expect(toggleValue(['gone'], 'b')).toEqual(['gone', 'b'])
    expect(toggleValue(['Nebius'], 'nebius')).toEqual([])
    expect(isSelected(['Nebius'], 'nebius')).toBe(true)
  })

  it('shows unlisted selected values as extra rows', () => {
    const rows = withSelectedExtras(normalizeOptions(['a']), ['a', 'gone'])
    expect(rows.map((r) => r.value)).toEqual(['a', 'gone'])
  })

  it('normalizes strings and keeps value apart from label', () => {
    expect(normalizeOptions(['x', { value: 'P1', label: 'P1 (15)' }])).toEqual([{ value: 'x', label: 'x' }, { value: 'P1', label: 'P1 (15)' }])
  })

  it('searches label and value, case-insensitively', () => {
    const opts = normalizeOptions([{ value: 'P1', label: 'P1 (15)' }, 'nebius'])
    expect(filterOptions(opts, 'NEB').map((o) => o.value)).toEqual(['nebius'])
    expect(filterOptions(opts, '').length).toBe(2)
    expect(filterOptions(opts, 'zzz')).toEqual([])
  })

  it('labels the closed button', () => {
    expect(summaryLabel([], 'All sources')).toBe('All sources')
    expect(summaryLabel(['nebius'])).toBe('nebius')
    expect(summaryLabel(['a', 'b', 'c'])).toBe('3 selected')
  })

  it('moves the focus index with the arrow keys and does not wrap', () => {
    expect(nextIndex(-1, 'ArrowDown', 3)).toBe(0)
    expect(nextIndex(2, 'ArrowDown', 3)).toBe(2)
    expect(nextIndex(0, 'ArrowUp', 3)).toBe(0)
    expect(nextIndex(-1, 'ArrowUp', 3)).toBe(2)
    expect(nextIndex(1, 'Home', 3)).toBe(0)
    expect(nextIndex(1, 'End', 3)).toBe(2)
    expect(nextIndex(0, 'ArrowDown', 0)).toBe(-1)
  })
})
