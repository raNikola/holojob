import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { buildBoard } from '../../src/modules/applications/boardModel.js'
import { activeStages, labelFor, retiredStages } from '../../src/modules/applications/stageRegistry.js'
import { newRequestId } from '../../src/modules/applications/trackerController.js'

let root
let server
const clock = new Date('2026-11-03T10:00:00.000Z')
const now = () => clock
const cache = () => client.getApplicationsState()
const storeFile = () => path.join(root, 'data/applications/applications.json')
const bytes = () => (fs.existsSync(storeFile()) ? fs.readFileSync(storeFile()) : null)
const sha = (b) => (b ? crypto.createHash('sha256').update(b).digest('hex') : null)
const keys = () => activeStages(cache().settings).map((s) => s.key)

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'appsettings-'))
  server = http.createServer(async (req, res) => {
    if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now }))) { res.statusCode = 418; res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  client.configureClient({ base: `http://127.0.0.1:${server.address().port}`, ensure: async () => true })
  await client.refreshApplications()
})

afterEach(async () => {
  client.configureClient()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

async function apply(n) {
  const jobId = crypto.createHash('sha256').update(`s-${n}`).digest('hex').slice(0, 16)
  const { application } = await client.createApplication({
    requestId: newRequestId(),
    jobId,
    posting: { jobId, title: `Role ${n}`, company: `Company ${n}`, jobUrl: `https://c${n}.example/${n}` },
    attempt: { channel: 'company_site', channelDetail: '', applicationUrl: '', appliedDate: '2026-10-20', cv: { kind: 'unknown' } },
  })
  return application
}

describe('board columns through the settings routes', () => {
  it('loads the default columns into the cache', () => {
    expect(keys()).toEqual(['screen', 'tech', 'onsite', 'offer'])
  })

  it('rename changes the label only: the key, the cards and the stored applications stay', async () => {
    const a = await apply(1)
    await client.moveApplication(a.id, { toStage: 'tech' })
    const before = sha(bytes())
    await client.changeStages({ op: 'rename', key: 'tech', label: 'Technical Interview' })
    expect(sha(bytes())).toBe(before)
    expect(keys()).toEqual(['screen', 'tech', 'onsite', 'offer'])
    expect(labelFor('tech', cache().settings)).toBe('Technical Interview')
    const col = buildBoard(cache().store, cache().settings, '2026-11-03').columns.find((c) => c.key === 'tech')
    expect([col.label, col.cards.length]).toEqual(['Technical Interview', 1])
  })

  it('reorders up and down without changing any key, and ignores a move at the edge', async () => {
    await client.changeStages({ op: 'move', key: 'offer', dir: 'up' })
    expect(keys()).toEqual(['screen', 'tech', 'offer', 'onsite'])
    await client.changeStages({ op: 'move', key: 'screen', dir: 'up' })
    expect(keys()).toEqual(['screen', 'tech', 'offer', 'onsite'])
  })

  it('adds a column with a new stable key; a second add with the same name is refused', async () => {
    await client.changeStages({ op: 'add', label: 'Take-home task' })
    expect(keys()).toContain('take_home_task')
    await expect(client.changeStages({ op: 'add', label: 'Take-Home Task' })).rejects.toMatchObject({ status: 409 })
  })

  it('remove retires: refused while open applications sit in it, then hides it and keeps the label', async () => {
    const a = await apply(1)
    await client.moveApplication(a.id, { toStage: 'onsite' })
    await expect(client.changeStages({ op: 'retire', key: 'onsite' })).rejects.toMatchObject({ status: 409, extra: { count: 1 }, message: 'Move the 1 application out first' })
    expect(keys()).toContain('onsite')
    await client.moveApplication(a.id, { toStage: 'offer' })
    const before = sha(bytes())
    await client.changeStages({ op: 'retire', key: 'onsite' })
    expect(sha(bytes())).toBe(before)
    expect(keys()).not.toContain('onsite')
    expect(retiredStages(cache().settings).map((s) => [s.key, s.label])).toEqual([['onsite', 'Onsite']])
    expect(labelFor('onsite', cache().settings)).toBe('Onsite')
  })

  it('adding the label of a removed column points to its key, and restoring brings it back', async () => {
    await client.changeStages({ op: 'retire', key: 'screen' })
    await expect(client.changeStages({ op: 'add', label: 'Screen' })).rejects.toMatchObject({ status: 409, extra: { retiredKey: 'screen' } })
    await client.changeStages({ op: 'unretire', key: 'screen' })
    expect(keys()).toContain('screen')
  })

  it('the last column cannot be removed, and the fixed ones are not editable', async () => {
    for (const key of ['screen', 'tech', 'onsite']) await client.changeStages({ op: 'retire', key })
    await expect(client.changeStages({ op: 'retire', key: 'offer' })).rejects.toMatchObject({ status: 400 })
    for (const key of ['applied', 'rejected', 'ghosted']) {
      await expect(client.changeStages({ op: 'rename', key, label: 'X' })).rejects.toMatchObject({ status: 400 })
      await expect(client.changeStages({ op: 'retire', key })).rejects.toMatchObject({ status: 400 })
    }
  })
})

describe('tracking switch', () => {
  it('off refuses moves and column changes but not the switch; on restores everything untouched', async () => {
    const a = await apply(1)
    await client.changeSwitches({ trackingEnabled: false })
    const before = sha(bytes())
    expect(cache().settings.trackingEnabled).toBe(false)
    await expect(client.moveApplication(a.id, { toStage: 'tech' })).rejects.toMatchObject({ status: 409 })
    await expect(client.changeStages({ op: 'rename', key: 'tech', label: 'T' })).rejects.toMatchObject({ status: 409 })
    expect(sha(bytes())).toBe(before)
    await client.changeSwitches({ trackingEnabled: true })
    await client.moveApplication(a.id, { toStage: 'tech' })
    expect(cache().settings.trackingEnabled).toBe(true)
  })
})
