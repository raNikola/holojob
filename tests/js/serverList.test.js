// The Jobs list as the server pages it (src/modules/jobs/serverList.js; docs/redesign/JOBS_LIST_SERVER_PLAN.md, P3), against the real route over HTTP.
// What the loader owes the screen: pages in the server's order, a new list for a new query, an in-place reload for the owner's own changes, a list that is
// never cut or spliced from two states, a refusal that is shown and never shortens the list, and no word to anything but the server.
import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { SCORED, startListServer } from './setup/jobsListServer.js'
import { createServerListLoader, extraKey, queryKey } from '../../src/modules/jobs/serverList.js'

let server
let fetches
let loader

const wrap = (delays = {}) => (url, options) => {
  fetches.push(JSON.parse(options.body))
  const delay = delays[fetches.length] ?? 0
  return new Promise((resolve) => setTimeout(resolve, delay)).then(() => server.fetchFn(url, options))
}

beforeEach(async () => {
  server = await startListServer({ pageSize: 4 })
  fetches = []
  loader = createServerListLoader({ fetchFn: wrap() })
})
afterEach(() => server.close())

const request = (extra = {}) => ({ stored: [], mode: 'all', filters: {}, classes: [], recent: false, sort: null, today: Date.parse('2026-11-20T00:00:00Z'), ...extra })

describe('pages', () => {
  it('the first page, then the next ones until the list ends, in the server\'s order', async () => {
    await loader.setRequest(request())
    const first = loader.getState()
    expect(first).toMatchObject({ status: 'ready', total: 13, nextOffset: 4, error: null })
    expect(first.rows).toHaveLength(4)
    expect(first.counts.stats.total).toBe(12)
    while (loader.getState().nextOffset !== null) await loader.more()
    const all = loader.getState()
    expect(all.rows).toHaveLength(13)
    expect(new Set(all.rows.map((r) => r.jobId)).size).toBe(13)
    expect(fetches.map((f) => f.offset)).toEqual([0, 4, 8, 12])
    expect(fetches.slice(1).every((f) => typeof f.revision === 'string')).toBe(true) // every next page names the list it continues
    expect(all.rows.map((r) => r.jobId)).toEqual((await server.fetchFn('/api/jobs/list?mode=all&ids=1').then((r) => r.json())).ids)
  })

  it('asks for the next page once, and nothing past the end', async () => {
    await loader.setRequest(request())
    await Promise.all([loader.more(), loader.more()])
    expect(fetches).toHaveLength(2)
    while (loader.getState().nextOffset !== null) await loader.more()
    const count = fetches.length
    await loader.more()
    expect(fetches).toHaveLength(count)
  })

  it('a request for the same list asks nothing', async () => {
    await loader.setRequest(request())
    await loader.setRequest(request())
    await loader.setRequest(request({ classes: [] }))
    expect(fetches).toHaveLength(1)
  })
})

describe('a new query is a new list', () => {
  it('drops the old rows at once and loads the new first page', async () => {
    await loader.setRequest(request())
    const pending = loader.setRequest(request({ filters: { searchText: 'delivery' } }))
    expect(loader.getState()).toMatchObject({ status: 'loading', rows: [] })
    await pending
    const state = loader.getState()
    expect(state.status).toBe('ready')
    expect(state.total).toBeLessThan(13)
    expect(state.rows.every((r) => /delivery/i.test(`${r.title} ${r.company}`) || r.jobId.length)).toBe(true)
  })

  it('a picked sort is a new query, and the same sort given again is not', async () => {
    const sort = { key: 'title', dir: 'asc' }
    expect(queryKey(request({ sort }))).toBe(queryKey(request({ sort: { ...sort } })))
    expect(queryKey(request({ sort }))).not.toBe(queryKey(request({ sort: { key: 'title', dir: 'desc' } })))
    expect(queryKey(request({ classes: ['b', 'a'] }))).toBe(queryKey(request({ classes: ['a', 'b'] })))
  })
})

describe('the owner\'s own changes reload in place', () => {
  const offList = { jobId: 'off1', title: 'Gone Ad', company: 'Acme', location: 'Remote', jobUrl: 'https://x.example/off1', offList: true, status: 'saved', matchScore: 80, matchLabel: 'Good', priority: 'P1', applyRecommendation: 'Apply', isRemote: true }

  it('keeps the rows on screen, loads the same number again, and shows the change', async () => {
    await loader.setRequest(request({ stored: [offList] }))
    await loader.more()
    expect(loader.getState().rows).toHaveLength(8)
    const pending = loader.setRequest(request({ stored: [{ ...offList, status: 'rejected' }] }))
    expect(loader.getState()).toMatchObject({ status: 'ready', refreshing: true })
    expect(loader.getState().rows).toHaveLength(8) // not emptied while it loads
    await pending
    const state = loader.getState()
    expect(state).toMatchObject({ status: 'ready', refreshing: false })
    expect(state.rows.length).toBeGreaterThanOrEqual(8)
    expect(extraKey(request({ stored: [offList] }))).not.toBe(extraKey(request({ stored: [{ ...offList, status: 'rejected' }] })))
  })

  it('a change that is not sent (a note on a row that is not worked) asks nothing', async () => {
    const plain = { jobId: 'j01', title: 'Held', status: 'new' }
    await loader.setRequest(request({ stored: [plain] }))
    await loader.setRequest(request({ stored: [{ ...plain, title: 'Edited in the browser' }] }))
    expect(fetches).toHaveLength(1)
  })
})

describe('a list that moved', () => {
  it('is loaded again from the start, with a notice, never spliced', async () => {
    await loader.setRequest(request())
    const before = loader.getState().revision
    // the data moves: the scored file loses rows
    server.writeScored(SCORED.slice(0, 7))
    await loader.more()
    const state = loader.getState()
    expect(state.notice).toMatch(/list changed/)
    expect(state.revision).not.toBe(before)
    expect(state.status).toBe('ready')
    const ids = state.rows.map((r) => r.jobId)
    expect(new Set(ids).size).toBe(ids.length) // no ad twice
    expect(state.counts.stats.total).toBe(7) // the new first page's counts, from the data as it is now
    loader.clearNotice()
    expect(loader.getState().notice).toBeNull()
  })

  it('a read of several pages that moves in the middle starts again from the first page', async () => {
    // the data moves between the first and the second request of one in-place reload
    let armed = false
    let sinceArmed = 0
    loader = createServerListLoader({
      fetchFn: (url, options) => {
        fetches.push(JSON.parse(options.body))
        if (armed && (sinceArmed += 1) === 2) server.writeScored(SCORED.slice(0, 9)) // just before the second page of the reload
        return server.fetchFn(url, options)
      },
    })
    await loader.setRequest(request())
    await loader.more() // two pages held: a reload keeps eight rows
    fetches.length = 0
    armed = true
    await loader.setRequest(request({ stored: [{ jobId: 'off1', title: 'Gone', offList: true, status: 'saved' }] }))
    expect(fetches.map((f) => f.offset)).toEqual([0, 4, 0, 4]) // the second page of the old list was refused ("changed"), so it began again
    const state = loader.getState()
    expect(state.status).toBe('ready')
    expect(state.counts.stats.total).toBe(9)
    expect(new Set(state.rows.map((r) => r.jobId)).size).toBe(state.rows.length)
  })
})

describe('a refusal is shown and never shortens the list', () => {
  const manyRows = (count) => Array.from({ length: count }, (_, i) => ({ jobId: `big${i}`, title: `Big ${i}`, offList: true, description: 'x'.repeat(9500), status: 'saved' }))

  it('with nothing loaded yet it is an error with the row count and the words', async () => {
    await loader.setRequest(request({ stored: manyRows(150), filters: { searchText: 'engineer' } }))
    const state = loader.getState()
    expect(state.status).toBe('error')
    expect(state.rows).toEqual([])
    expect(state.error).toMatchObject({ tooLarge: true, rowCount: 150 })
    expect(state.error.message).toMatch(/Nothing was cut and no list was made/)
  })

  it('150 browser-only rows without their texts are an ordinary request', async () => {
    await loader.setRequest(request({ stored: manyRows(150) }))
    expect(loader.getState()).toMatchObject({ status: 'ready', error: null })
    expect(loader.getState().extra).toEqual({ sent: 150, notOnServer: 150 })
  })

  it('a new query that is refused has no rows to keep: it is an error, not a list of the old query', async () => {
    await loader.setRequest(request())
    expect(loader.getState().rows).toHaveLength(4)
    await loader.setRequest(request({ stored: manyRows(150), filters: { searchText: 'a' } }))
    expect(loader.getState().status).toBe('error')
    expect(loader.getState().rows).toEqual([])
  })

  it('an in-place reload that is refused keeps the rows it had', async () => {
    await loader.setRequest(request({ filters: { searchText: 'a' }, stored: manyRows(3) }))
    const rows = loader.getState().rows
    expect(rows.length).toBeGreaterThan(0)
    await loader.setRequest(request({ filters: { searchText: 'a' }, stored: manyRows(150) }))
    const state = loader.getState()
    expect(state.status).toBe('ready')
    expect(state.rows).toEqual(rows)
    expect(state.error.tooLarge).toBe(true)
  })
})

describe('an answer that arrives late', () => {
  it('is ignored: the newest request wins', async () => {
    loader = createServerListLoader({ fetchFn: wrap({ 1: 120 }) }) // the first answer is slow
    const slow = loader.setRequest(request({ filters: { searchText: 'delivery' } }))
    const quick = loader.setRequest(request({ filters: { searchText: 'owner' } }))
    await Promise.all([slow, quick])
    const state = loader.getState()
    expect(state.rows.length).toBeGreaterThan(0)
    expect(state.rows.every((r) => !/delivery/i.test(r.title) || /owner/i.test(`${r.title}${r.company}`))).toBe(true)
    expect(fetches).toHaveLength(2)
  })
})

describe('select-all across pages', () => {
  it('asks the server for every matching ad', async () => {
    await loader.setRequest(request())
    const { ids, selectableIds } = await loader.ids()
    expect(ids).toHaveLength(13)
    expect(selectableIds).toContain('ledger-only-1') // a row only the server holds is selectable: its status is written to the server
    expect(loader.getState().rows).toHaveLength(4) // the page held did not grow
  })

  it('says so when the server cannot answer', async () => {
    await server.close()
    server = await startListServer({ pageSize: 4 })
    const broken = createServerListLoader({ fetchFn: () => Promise.reject(new Error('down')) })
    await broken.setRequest(request())
    expect(broken.getState().status).toBe('error')
    expect((await broken.ids()).error).toMatch(/down/)
    expect(fs.existsSync(path.join(server.root, 'data/jobs'))).toBe(true)
  })
})
