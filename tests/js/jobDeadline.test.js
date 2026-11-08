import { describe, expect, it } from 'vitest'
import { dayOf, deadlineSortValue, deadlineStatus } from '../../src/modules/jobs/jobDeadline.js'
import { sortRows, nextSort } from '../../src/modules/tableSort.js'

const TODAY = new Date(2026, 10, 8, 15, 30).getTime()
const on = (date, extra = {}) => ({ applyDeadline: date, applyDeadlineSource: 'board', ...extra })

describe('deadline status', () => {
  it.each([
    ['2026-11-08', 'critical', 'Today', 'warn'],
    ['2026-11-09', 'critical', 'Tomorrow', 'warn'],
    ['2026-11-10', 'warning', 'In 2 days', 'medium'],
    ['2026-11-11', 'warning', 'In 3 days', 'medium'],
    ['2026-11-12', 'upcoming', 'In 4 days', 'derived'],
    ['2026-11-15', 'upcoming', 'In 7 days', 'derived'],
    ['2026-11-16', 'later', 'Nov 16, 2026', null],
    ['2026-11-07', 'expired', 'Expired', 'low'],
  ])('%s reads %s / %s', (date, key, label, variant) => {
    expect(deadlineStatus(on(date), TODAY)).toMatchObject({ key, label, variant })
  })

  it.each([[{}], [{ applyDeadline: null }], [{ applyDeadline: 'soon' }], [{ applyDeadline: '2026-02-31' }]])('%j is Not specified', (job) => {
    expect(deadlineStatus(job, TODAY)).toMatchObject({ key: 'unknown', label: 'Not specified', variant: null })
  })

  it('a board expiry on a row the route gave, before any scoring, counts', () => {
    expect(deadlineStatus({ expiresAt: '2026-11-08' }, TODAY).label).toBe('Today')
  })

  it('the time of day plays no part', () => {
    const lateAtNight = new Date(2026, 10, 8, 23, 59).getTime()
    expect(deadlineStatus(on('2026-11-09'), lateAtNight).label).toBe('Tomorrow')
    expect(deadlineStatus(on('2026-11-09'), dayOf(lateAtNight)).label).toBe('Tomorrow')
  })

  it('says an expired ad is not closed by that', () => {
    expect(deadlineStatus(on('2026-11-01'), TODAY).note).toContain('not marked closed')
  })
})

describe('deadline sort', () => {
  const columns = { deadline: { type: 'number', firstDir: 'asc', value: (j) => deadlineSortValue(j, TODAY) } }
  const rows = [{ id: 'unknown' }, { id: 'past', ...on('2026-11-01') }, { id: 'far', ...on('2026-12-01') }, { id: 'soon', ...on('2026-11-09') }]

  it('starts soonest first', () => {
    expect(nextSort({ key: 'x', dir: 'desc' }, 'deadline', columns)).toEqual({ key: 'deadline', dir: 'asc' })
  })

  it('soonest, then later, then expired, and no date last', () => {
    expect(sortRows(rows, { key: 'deadline', dir: 'asc' }, columns).map((r) => r.id)).toEqual(['soon', 'far', 'past', 'unknown'])
  })

  it('no date stays last the other way too', () => {
    expect(sortRows(rows, { key: 'deadline', dir: 'desc' }, columns).at(-1).id).toBe('unknown')
  })
})
