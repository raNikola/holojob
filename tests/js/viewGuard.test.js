// The Node side of the ledger/view check (python/job_scoring/view_guard.py is the other): the same cases, and the rebuild call.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ViewUnrecoverable, ensureViewCurrent, viewPaths, viewState, viewUnrecoverableAnswer } from '../../scripts/view-guard.js'

const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/view-generation.json', import.meta.url), 'utf-8'))
let root

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'view-guard-'))
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
})
afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

function place({ ledger, view }) {
  const { jobsFile, ledgerFile } = viewPaths(root)
  if (ledger !== null) fs.writeFileSync(ledgerFile, ledger + ' '.repeat(10))
  if (view !== null) fs.writeFileSync(jobsFile, view + ' '.repeat(10))
}

/** A child process that answers with `stdout` and exits with `code`. */
function fakeSpawn(stdout, code) {
  const calls = []
  const spawnFn = (python, args, options) => {
    calls.push({ python, args, options })
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(stdout)); child.emit('close', code) })
    return child
  }
  return { spawnFn, calls }
}

describe('viewState: the cases both languages run', () => {
  for (const c of fixture.cases) {
    it(c.name, () => {
      place(c)
      expect(viewState(viewPaths(root)).consistent).toBe(c.consistent)
    })
  }

  it('says which generations it saw', () => {
    place({ ledger: '{\n  "generation": 7,\n  "jobs": {}\n}', view: '{"meta": {"ledgerGeneration": 6, "x": 1}}' })
    expect(viewState(viewPaths(root))).toEqual({ consistent: false, ledgerGeneration: 7, viewGeneration: 6 })
  })
})

describe('ensureViewCurrent', () => {
  it('starts no process when the view is the ledger\'s', async () => {
    place(fixture.cases[0])
    const { spawnFn, calls } = fakeSpawn('', 0)
    expect(await ensureViewCurrent({ root, spawnFn })).toEqual({ regenerated: false })
    expect(calls).toHaveLength(0)
  })

  it('asks Python to rebuild a view that is behind, and passes the job file', async () => {
    place(fixture.cases[1])
    const { spawnFn, calls } = fakeSpawn('{"ok": true, "regenerated": true}\n', 0)
    expect(await ensureViewCurrent({ root, python: 'py', script: 'guard.py', spawnFn })).toEqual({ regenerated: true })
    expect(calls).toHaveLength(1)
    expect(calls[0].python).toBe('py')
    expect(calls[0].args).toEqual(['guard.py', 'ensure', '--jobs', viewPaths(root).jobsFile])
  })

  it('rejects with Python\'s own reason when the view cannot be rebuilt, and the caller serves nothing', async () => {
    place(fixture.cases[1])
    const { spawnFn } = fakeSpawn('{"ok": false, "error": "view_unrecoverable", "message": "the ledger cannot be read"}\n', 1)
    const error = await ensureViewCurrent({ root, spawnFn }).catch((e) => e)
    expect(error).toBeInstanceOf(ViewUnrecoverable)
    expect(error.message).toBe('the ledger cannot be read')
    expect(viewUnrecoverableAnswer(error)).toEqual({ ok: false, error: 'view_unrecoverable', message: 'the ledger cannot be read' })
  })

  it('rejects when the rebuild exits without an answer, or cannot start', async () => {
    place(fixture.cases[1])
    expect((await ensureViewCurrent({ root, spawnFn: fakeSpawn('', 1).spawnFn }).catch((e) => e)).message).toMatch(/exit 1/)
    const throwing = () => { throw new Error('no such file') }
    expect((await ensureViewCurrent({ root, spawnFn: throwing }).catch((e) => e)).message).toMatch(/could not start: no such file/)
  })

  it('treats an exit 0 with an answer that is not ok as a failure', async () => {
    place(fixture.cases[1])
    const error = await ensureViewCurrent({ root, spawnFn: fakeSpawn('{"ok": false, "message": "no"}\n', 0).spawnFn }).catch((e) => e)
    expect(error).toBeInstanceOf(ViewUnrecoverable)
  })
})
