import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import { filterJobs, normalizePriorityFilter } from '../../src/modules/jobs/jobFilters.js'
import { NAV_ITEMS, VIEWS } from '../../src/modules/appNavigation.js'

const jobs = ['P1', 'P2', 'P3', 'P1', 'Reject'].map((priority, i) => ({ jobId: String(i), priority }))
const ids = (list) => list.map((j) => j.jobId)

describe('priority filter', () => {
  it('keeps jobs matching any selected priority', () => {
    expect(ids(filterJobs(jobs, { priority: ['P1', 'P2'] }))).toEqual(['0', '1', '3'])
    expect(ids(filterJobs(jobs, { priority: ['P3'] }))).toEqual(['2'])
  })

  it('an empty selection shows everything', () => {
    expect(filterJobs(jobs, { priority: [] })).toHaveLength(5)
    expect(filterJobs(jobs, {})).toHaveLength(5)
  })

  it('reads a string saved by the old single-select as a list of one', () => {
    expect(normalizePriorityFilter('P2')).toEqual(['P2'])
    expect(normalizePriorityFilter('')).toEqual([])
    expect(normalizePriorityFilter(undefined)).toEqual([])
    expect(ids(filterJobs(jobs, { priority: 'P2' }))).toEqual(['1'])
  })
})

describe('Peer Chat is gone', () => {
  it('has no view, nav item or chat module', () => {
    expect(VIEWS.PEER_CHAT).toBeUndefined()
    expect(NAV_ITEMS.some((i) => /chat/i.test(i.label))).toBe(false)
    for (const p of ['src/components/chat', 'src/context/ChatContext.jsx', 'scripts/chat-server.js', 'scripts/chat-store.js']) {
      expect(fs.existsSync(p), p).toBe(false)
    }
    const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'))
    expect(Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).filter((d) => d.startsWith('socket.io'))).toEqual([])
  })
})
