// @vitest-environment jsdom
// Mark Applied on an ad that exists only in this browser (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b, owner decision 2026-11-24): open it from local data,
// Mark Applied, the application is kept on the server and shows on the Board; the paged list then says Applied. The tracker's own handler runs for real over a
// temp data dir, with the real client, the real browser store (jsdom) and the real list route.
import fs from 'node:fs'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startListServer } from './setup/jobsListServer.js'
import { configureClient, getApplicationsState, refreshApplications } from '../../src/modules/applications/applicationsClient.js'
import { buildBoard } from '../../src/modules/applications/boardModel.js'
import { markApplied, newApplicationDefaults, panelMode } from '../../src/modules/applications/trackerController.js'
import { buildListBody, fetchListPage, openAd } from '../../src/modules/jobs/jobListClient.js'
import { JOBS_STORAGE_KEY, getDefaultJobsState, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'

const SECRET = 'PRIVATE-NOTE-5503'
const OFF = { jobId: 'off1', title: 'Gone Ad', company: 'Acme', location: 'Remote', jobUrl: 'https://x.example/off1', offList: true, status: 'saved', matchScore: 80, matchLabel: 'Good', priority: 'P1', applyRecommendation: 'Apply', isRemote: true, description: 'The ad text.', notes: SECRET }
const MAN = { jobId: 'man1', title: 'My own job', company: 'Me', location: 'Remote', jobUrl: 'https://y.example/man1', manualEntry: true, provider: 'manual', site: 'manual', description: 'my text', status: 'new', notes: SECRET, extraLinks: [SECRET], sourceUrl: `https://${SECRET}.example/` }

let server
let fetchFn

beforeEach(async () => {
  localStorage.clear()
  server = await startListServer({ pageSize: 50, withApplications: true })
  fetchFn = (url, options) => server.fetchFn(url, options)
  configureClient({ fetch: fetchFn, base: '', ensure: async () => true })
  saveJobs({ ...getDefaultJobsState(), jobs: [OFF, MAN] })
})
afterEach(async () => {
  vi.restoreAllMocks()
  configureClient()
  await server.close()
})

const storedNow = () => loadJobs().jobs
const applicationsFile = () => fs.readFileSync(path.join(server.root, 'data/applications/applications.json'), 'utf-8')

async function markAppliedOnLocalAd(jobId) {
  await refreshApplications()
  const opened = await openAd({ jobId, stored: storedNow(), fetchFn })
  expect(opened).toMatchObject({ source: 'local', readOnly: false }) // the server does not hold it: it opens from the browser's own row
  const cache = getApplicationsState()
  expect(panelMode(opened.row, cache).mode).toBe('new')
  const result = await markApplied(opened.row, cache, newApplicationDefaults(opened.row, null))
  return { opened, result }
}

describe('Mark Applied on an ad only this browser has', () => {
  it.each([['an off-list ad', 'off1', 'Gone Ad', 'Acme'], ['a hand-entered job', 'man1', 'My own job', 'Me']])('%s: the application is kept on the server and shows on the Board', async (_name, jobId, title, company) => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const { result } = await markAppliedOnLocalAd(jobId)
    expect(result.application.posting).toMatchObject({ jobId, title, company, capturedFrom: 'browser' })

    // kept: it is in the server's file, with the ad's own fields and nothing of the owner's notes, links or source address
    const text = applicationsFile()
    expect(JSON.parse(text).applications[result.application.id].posting.jobId).toBe(jobId)
    expect(text).not.toContain(SECRET)

    // on the Board: a fresh read of the store, as the Board does, has a card for it in the first column
    configureClient({ fetch: fetchFn, base: '', ensure: async () => true })
    await refreshApplications()
    const { store, settings } = getApplicationsState()
    const board = buildBoard(store, settings, new Date().toISOString().slice(0, 10))
    const cards = board.columns.flatMap((column) => column.cards.map((card) => ({ ...card, column: column.key })))
    expect(cards.filter((card) => card.jobId === jobId)).toEqual([expect.objectContaining({ title, company, column: 'applied' })])
    expect(board.total).toBe(1)

    // marking it applied writes nothing to the browser's list: the stored row is as it was
    expect(setItem).not.toHaveBeenCalled()
    expect(storedNow().find((job) => job.jobId === jobId)).toEqual(expect.objectContaining({ status: jobId === 'off1' ? 'saved' : 'new' }))
    expect(localStorage.getItem(JOBS_STORAGE_KEY)).toContain(jobId)
  })

  it('the paged list then says Applied for it, and the Applied filter finds it', async () => {
    await markAppliedOnLocalAd('off1')
    const all = await fetchListPage(buildListBody({ stored: storedNow(), mode: 'all' }), fetchFn)
    expect(all.page.rows.find((row) => row.jobId === 'off1')).toMatchObject({ status: 'applied_manually' })
    const applied = await fetchListPage(buildListBody({ stored: storedNow(), mode: 'all', filters: { status: 'applied' } }), fetchFn)
    expect(applied.page.rows.map((row) => row.jobId)).toEqual(['off1'])
    expect(applied.page.counts.stats.crmApplied).toBe(1)
  })

  it('a second Mark Applied on the same ad is the same application: a retry cannot make two', async () => {
    const { opened } = await markAppliedOnLocalAd('off1')
    const cache = getApplicationsState()
    expect(panelMode(opened.row, cache).mode).toBe('tracked')
    expect(Object.keys(JSON.parse(applicationsFile()).applications)).toHaveLength(1)
  })
})
