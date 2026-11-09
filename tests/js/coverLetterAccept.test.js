// Accepting an AI cover letter: the server checks its own draft; the request carries the id and the confirmation only.
import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import { acceptCoverLetter } from '../../scripts/ai-draft-accept.js'

function fakeSpawn(answer, { code = 0, error = false } = {}) {
  const calls = []
  const spawnFn = (python, args, options) => {
    calls.push({ python, args, options })
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    setImmediate(() => {
      if (error) { child.emit('error', new Error('boom')); return }
      if (answer !== undefined) child.stdout.emit('data', Buffer.from(`${typeof answer === 'string' ? answer : JSON.stringify(answer)}\n`))
      child.emit('close', code)
    })
    return child
  }
  return { spawnFn, calls }
}

describe('acceptCoverLetter', () => {
  it('refuses without confirm: true and starts nothing', async () => {
    for (const confirm of [undefined, false, 'true', 1]) {
      const { spawnFn, calls } = fakeSpawn({ ok: true })
      const r = await acceptCoverLetter({ jobId: 'job-1', confirm }, { spawnFn })
      expect(r.status).toBe(409)
      expect(r.body.error).toBe('confirm_required')
      expect(calls).toEqual([])
    }
  })

  it.each([undefined, '', '..', '.', 'a/b', '../x', 'a b', 5, { a: 1 }])('refuses the job id %j', async (jobId) => {
    const { spawnFn, calls } = fakeSpawn({ ok: true })
    const r = await acceptCoverLetter({ jobId, confirm: true }, { spawnFn })
    expect(r.status).toBe(400)
    expect(calls).toEqual([])
  })

  it('runs the checker with the job id only: no text from the request reaches it', async () => {
    const { spawnFn, calls } = fakeSpawn({ ok: true, passed: true, file: 'ai_cover_letter.md' })
    const r = await acceptCoverLetter({ jobId: 'job-1', confirm: true, text: 'IGNORED LETTER', content: 'IGNORED' }, { spawnFn, python: 'py', script: 'check.py' })
    expect(r).toEqual({ status: 200, body: { ok: true, passed: true, file: 'ai_cover_letter.md' } })
    expect(calls).toHaveLength(1)
    expect(calls[0].args).toEqual(['check.py', '--job-id', 'job-1'])
    expect(JSON.stringify(calls)).not.toContain('IGNORED')
  })

  it('answers 422 with the issues when the facts are not verified', async () => {
    const { spawnFn } = fakeSpawn({ ok: false, error: 'facts_not_verified', issues: ['Unverified number: 47'] })
    const r = await acceptCoverLetter({ jobId: 'job-1', confirm: true }, { spawnFn })
    expect(r.status).toBe(422)
    expect(r.body).toMatchObject({ ok: false, error: 'facts_not_verified', issues: ['Unverified number: 47'] })
  })

  it.each([['no_draft', 404], ['no_profile', 409], ['invalid_job', 400]])('maps %s to %i', async (error, status) => {
    const { spawnFn } = fakeSpawn({ ok: false, error })
    expect((await acceptCoverLetter({ jobId: 'job-1', confirm: true }, { spawnFn })).status).toBe(status)
  })

  it('a checker that fails or prints nothing readable is a refusal, never a pass', async () => {
    for (const setup of [fakeSpawn(undefined), fakeSpawn('not json'), fakeSpawn(undefined, { error: true }), fakeSpawn({ ok: false })]) {
      const r = await acceptCoverLetter({ jobId: 'job-1', confirm: true }, { spawnFn: setup.spawnFn })
      expect(r.status).toBe(500)
      expect(r.body.ok).toBe(false)
    }
  })
})

vi.setConfig({ testTimeout: 10000 })
