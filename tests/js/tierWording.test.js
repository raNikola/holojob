// Option A wording (owner decision 2026-11-21): counts are tier counts, and no label presents P1 as the best fit.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import BulkActionsBar from '../../src/components/jobs/BulkActionsBar.jsx'
import JobDiscoverySummary from '../../src/components/jobs/JobDiscoverySummary.jsx'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { describeRun } from '../../src/modules/jobs/pipelineSummary.js'

const ad = (jobId, matchScore, extra = {}) => ({ jobId, title: jobId, company: 'Acme', jobUrl: `https://x.example/${jobId}`, status: 'new', matchScore, ...extra })

describe('tier counts replace the P1 / P2 / P3 count cards', () => {
  const jobs = [
    ad('a', 90, { priority: 'P1' }), ad('b', 72, { priority: 'P2' }), ad('c', 60, { priority: 'P2' }), ad('d', 45, { priority: 'P3' }),
    ad('e', 88, { priority: 'Blocked', blockedBy: [{ kind: 'location', text: 'x' }] }), ad('f', 80, { isClosed: true }),
  ]

  it('computeJobStats counts the open ads of each tier; blocked, closed and unscored ads are in none', () => {
    const stats = computeJobStats(jobs)
    expect([stats.strong, stats.possible, stats.weak]).toEqual([2, 1, 1])
  })

  it('the summary shows the tier names and no priority cards', () => {
    const html = renderToStaticMarkup(createElement(JobDiscoverySummary, { stats: computeJobStats(jobs), meta: null }))
    for (const label of ['Strong fit', 'Possible fit', 'Weak fit']) expect(html).toContain(label)
    expect(html).not.toMatch(/>P[123]</)
  })
})

describe('actions say what they do', () => {
  it('the bulk P1 action says it takes the first P1 jobs in file order and does not call them best', () => {
    const html = renderToStaticMarkup(createElement(BulkActionsBar, { selectedCount: 1, jobs: [], selectedJobIds: new Set() }))
    expect(html).toContain('first 50 P1 jobs, in file order')
    expect(html).not.toMatch(/\b(best|top)\b/i)
  })

  it('the pipeline line gives no P1 / P2 counts, and none without the scored rows', () => {
    const line = describeRun({ scoring: { jobs: 5, priority: { P1: 3, P2: 2 } } }, 5)
    expect(line).not.toContain('P1')
  })
})
