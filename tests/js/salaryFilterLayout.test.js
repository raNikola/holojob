import { beforeAll, describe, expect, it } from 'vitest'
import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { CLEAR_ALL_FILTERS } from '../../src/modules/jobs/jobFilters.js'
import { withProfileSalaryDefaults } from '../../src/modules/jobs/jobSalary.js'
import { salaryRangeOf } from '../../src/modules/jobs/salaryFilter.js'

// The test runner compiles JSX with the classic runtime, which needs React in scope.
let SalaryFilter
beforeAll(async () => {
  globalThis.React = React
  SalaryFilter = (await import('../../src/components/jobs/SalaryFilter.jsx')).default
})

const bp = { minSalaryEur: 1500, desiredSalaryMinEur: 2000, desiredSalaryMaxEur: 2500 }

function box(rawFilters) {
  const filters = withProfileSalaryDefaults(rawFilters, bp)
  const { from, to } = salaryRangeOf(filters)
  const html = renderToStaticMarkup(createElement(SalaryFilter, { from, to, includeUnknown: true, filters, profile: bp, onChange: () => {} }))
  const group = html.slice(html.indexOf('role="group"'), html.indexOf('class="sr-only"'))
  return group
    .replace(/value="[^"]*"/g, '')
    .replace(/ disabled=""/g, '')
    .replace(/ invisible/g, '')
    .replace(/_R_[0-9a-z]+_/g, 'ID')
    .replace(/ "/g, '"')
}

describe('Salary box layout', () => {
  it('has the same elements and classes in the untouched, set and cleared states', () => {
    const untouched = box({})
    expect(box({ salaryMode: 'set', salaryFrom: 3000, salaryTo: 4000 })).toBe(untouched)
    expect(box({ ...CLEAR_ALL_FILTERS })).toBe(untouched)
  })

  it('always renders the clear and reset slots, hiding them with visibility only', () => {
    const html = renderToStaticMarkup(createElement(SalaryFilter, { from: null, to: null, includeUnknown: true, filters: withProfileSalaryDefaults({ ...CLEAR_ALL_FILTERS }, {}), profile: {}, onChange: () => {} }))
    expect(html).toContain('aria-label="Clear salary range"')
    expect(html).toContain('aria-label="Reset salary to your profile values"')
    expect((html.match(/invisible/g) || []).length).toBe(2)
  })
})
