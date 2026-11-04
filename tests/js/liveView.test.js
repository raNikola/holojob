import { describe, expect, it } from 'vitest'
import { CANCEL_REQUESTED_TEXT, classifyCancel, currentStepText, elapsedText, liveSourceRows } from '../../src/modules/activity/liveView.js'
import { ev, liveBody, record, running, start } from './setup/activityFixtures.js'

const projected = (rec, options) => liveBody(rec, options).run

describe('the source rows of a running run', () => {
  it('fills in as events arrive: Reading, then the figures', () => {
    const run = projected(running())
    const reading = liveSourceRows(run, liveBody(running(), { events: [ev('source_start', { source: 'jobspy' })] }).events)
    expect(reading).toEqual([{ name: 'jobspy', state: 'Reading…', reading: true, returned: '–', collected: '–' }])
    const done = liveSourceRows(run, liveBody(running(), { events: [ev('source_start', { source: 'jobspy' }), ev('source_end', { source: 'jobspy', status: 'ok', read: 120, kept: 40 })] }).events)
    expect(done).toEqual([{ name: 'jobspy', state: 'OK', reading: false, returned: '120', collected: '40' }])
  })

  it('prefers the record\'s row to the event once the record has it, and keeps source order', () => {
    const rec = running(9, { sources: [{ name: 'jobspy', status: 'ok', read: 100, kept: 40, new: 1 }] })
    const events = liveBody(rec, { events: [ev('source_start', { source: 'jobspy' }), ev('source_end', { source: 'jobspy', status: 'ok', read: 1, kept: 1 }), ev('source_start', { source: 'infostud' })] }).events
    const rows = liveSourceRows(projected(rec), events)
    expect(rows.map((r) => [r.name, r.state, r.returned])).toEqual([['jobspy', 'OK', '100'], ['infostud', 'Reading…', '–']])
  })

  it('a failed or skipped source is named as such, an unreported number is not 0', () => {
    const events = liveBody(running(), { events: [ev('source_end', { source: 'a', status: 'failed' }), ev('source_end', { source: 'b', status: 'skipped', read: 0, kept: 0 })] }).events
    const rows = liveSourceRows(projected(running()), events)
    expect(rows.map((r) => [r.name, r.state, r.returned])).toEqual([['a', 'Failed', 'Not recorded'], ['b', 'Skipped', '0']])
  })

  it('has no rows before anything reports', () => {
    expect(liveSourceRows(projected(running()), [])).toEqual([])
    expect(liveSourceRows(null, null)).toEqual([])
  })
})

describe('time and step', () => {
  it('says how long the run has gone, as of the last answer', () => {
    const run = projected(running(9))
    expect(elapsedText(run, Date.parse(start(9)) + 130000)).toBe('Running for 2 min 10 s')
    expect(elapsedText(run, Date.parse(start(9)) - 5000)).toBe('Running for 0 s')
    expect(elapsedText(run, null)).toBeNull()
    expect(elapsedText({ startedAt: null }, Date.now())).toBeNull()
  })

  it('names the step that is running', () => {
    expect(currentStepText(projected(running()))).toBe('Reading the sources')
    expect(currentStepText(projected(running(9, { steps: [{ name: 'discovery', status: 'ok' }, { name: 'scoring', status: 'running' }] })))).toBe('Scoring the jobs')
    expect(currentStepText(projected(record(1)))).toBeNull()
  })
})

describe('what the server said to a cancel', () => {
  it('a request on file is only a request', () => {
    expect(classifyCancel({ status: 202, body: { ok: true, result: 'cancel_requested' } })).toEqual({ kind: 'requested', message: CANCEL_REQUESTED_TEXT })
    expect(classifyCancel({ status: 200, body: { ok: true, result: 'cancel_already_requested', message: 'A cancel was already requested for this run.' } }).kind).toBe('requested')
    expect(CANCEL_REQUESTED_TEXT).toBe('Cancel requested. The run stops at its next safe point.')
    expect(CANCEL_REQUESTED_TEXT).not.toMatch(/stopped|cancelled/i)
  })

  it('a run that is no longer going settles, with the server\'s own words', () => {
    for (const result of ['already_cancelled', 'already_finished', 'not_running']) {
      expect(classifyCancel({ status: 200, body: { ok: true, result, message: `msg ${result}` } })).toEqual({ kind: 'settled', message: `msg ${result}` })
    }
  })

  it('a refusal says nothing changed', () => {
    expect(classifyCancel({ status: 409, body: { message: 'Only a Re-scrape can be cancelled. Nothing changed.' } })).toEqual({ kind: 'refused', message: 'Only a Re-scrape can be cancelled. Nothing changed.' })
    expect(classifyCancel({ status: 404, body: { message: 'There is no such run.' } }).kind).toBe('refused')
    expect(classifyCancel({ status: 500, body: {} }).message).toMatch(/status 500.*Nothing changed/)
  })
})
