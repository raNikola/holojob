import { describe, expect, it } from 'vitest'
import { activeFilterChips, filterJobs, CLEAR_ALL_FILTERS } from '../../src/modules/jobs/jobFilters.js'
import { roleClassBadge, roleClassOf } from '../../src/modules/jobs/roleClass.js'
import { importJobsFromFile } from '../../src/modules/jobs/jobStorage.js'

const job = (jobId, roleClass, extra = {}) => ({ jobId, title: jobId, company: 'Acme', status: 'new', matchScore: 50, ...(roleClass ? { roleClass } : {}), ...extra })

describe('role class (badge and filter only)', () => {
  const jobs = [job('a', 'target'), job('b', 'adjacent'), job('c', 'other'), job('d', 'not available'), job('e')]

  it('a row without the field, or with an unknown value, reads as not available', () => {
    expect(roleClassOf(job('x'))).toBe('not available')
    expect(roleClassOf(job('x', 'bogus'))).toBe('not available')
    expect(roleClassBadge(job('x', 'target', { roleName: 'Product Manager' })).reason).toContain('Product Manager')
  })

  it.each([['target', ['a']], ['adjacent', ['b']], ['other', ['c']], ['not available', ['d', 'e']]])('filter %s', (value, ids) => {
    expect(filterJobs(jobs, { roleClass: value }).map((j) => j.jobId)).toEqual(ids)
  })

  it('no filter keeps every row in its order, and the filter has a chip that clears it', () => {
    expect(filterJobs(jobs, {}).map((j) => j.jobId)).toEqual(['a', 'b', 'c', 'd', 'e'])
    const chip = activeFilterChips({ roleClass: 'target' }).find((c) => c.key === 'roleClass')
    expect(chip.label).toBe('Role class: Target role')
    expect(chip.patch).toEqual({ roleClass: '' })
    expect(CLEAR_ALL_FILTERS.roleClass).toBe('')
  })

  it('the stamped field survives an import of the scored file', () => {
    const file = { meta: {}, jobs: [{ jobId: 'a', title: 'PM', company: 'Acme', jobUrl: 'https://x.test/a', roleClass: 'target', roleName: 'Product Manager' }] }
    const { jobs: rows } = importJobsFromFile(file, null)
    expect(rows[0].roleClass).toBe('target')
    expect(rows[0].roleName).toBe('Product Manager')
  })
})
