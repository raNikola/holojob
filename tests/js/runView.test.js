// The wording of the Activity screen (S7b), as pure functions. The screen itself is in activityScreen.dom.test.js.
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { NOT_RECORDED, NUMBER_HELP, SOURCE_STATUS_TONES, SOURCE_NEW_NOTE, filterReasonText, formatDuration, ledgerText, proofView, reasonText, savedShort, savedText, scoringText, show, sourceStatusLabel, stagingText, statusLabel, statusSentence } from '../../src/modules/activity/runView.js'
import { answer, importBlock, record } from './setup/activityFixtures.js'

const run = (extra, n = 1) => answer([record(n, extra)]).runs[0]
const table = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, '../../src/data/proofReasons.json'), 'utf-8'))

describe('numbers', () => {
  it('shows a number the API gave, and Not recorded for what it did not; null is never 0', () => {
    expect(show(0)).toBe('0')
    expect(show(1469)).toBe((1469).toLocaleString())
    for (const missing of [null, undefined, NaN, 'x']) expect(show(missing)).toBe(NOT_RECORDED)
    expect(formatDuration(null)).toBe(NOT_RECORDED)
    expect(formatDuration(0)).toBe('0 s')
    expect(formatDuration(90)).toBe('1 min 30 s')
    expect(formatDuration(3720)).toBe('1 h 2 min')
  })

  it('names the six numbers once each, with a one-line help', () => {
    expect(NUMBER_HELP.map(([label]) => label)).toEqual(['Returned', 'Filtered out', 'Collected', 'Saved', 'New', 'Refreshed'])
    for (const [, help] of NUMBER_HELP) expect(help).not.toMatch(/\n/)
  })

  it('Saved shows its parts', () => {
    expect(savedText(run({ import: importBlock({ saved: 455, new: 3, refreshed: 452 }) }))).toBe('Saved 455 (3 new, 452 already known and refreshed)')
    expect(savedShort(run({ import: importBlock({ saved: 455, new: 3, refreshed: 452 }) }))).toBe('455 (3 new)')
  })

  it('a cancelled run adds that nothing else changed', () => {
    const cancelled = run({ status: 'cancelled', cancel: { requestedAt: null, outcome: 'collected_ads_saved', saved: 455 }, import: importBlock({ kind: 'partial', saved: 455, new: 3, refreshed: 452, ledger: undefined }) })
    expect(savedText(cancelled)).toBe('Saved 455 (3 new, 452 already known and refreshed). Nothing else changed.')
  })

  it('a record with no saved figure says Not recorded, never Saved 0', () => {
    const old = run({})
    expect(savedText(old)).toBe('Saved: Not recorded')
    expect(savedShort(old)).toBe(NOT_RECORDED)
    expect(savedText(run({ import: importBlock({ saved: 12, new: null, refreshed: null }) }))).toBe('Saved 12')
  })

  it('a cancelled run that had to be killed says nothing was saved because its outcome says so', () => {
    expect(savedText(run({ status: 'cancelled', cancel: { requestedAt: null, outcome: 'stopped_nothing_imported' } }))).toBe('Nothing was saved. Nothing else changed.')
  })
})

describe('what a run says in words', () => {
  it('labels every status, and an unknown one as Unknown', () => {
    expect(['ok', 'partial', 'failed', 'skipped', 'running', 'interrupted', 'cancelled'].map(statusLabel)).toEqual(['OK', 'Partial', 'Failed', 'Skipped', 'Running', 'Interrupted', 'Cancelled'])
    expect(statusLabel('whatever')).toBe('Unknown')
  })

  it('a run that imported nothing because no source was usable says so, and a skipped one stays skipped', () => {
    const nothing = { kind: 'nothing', nothingSaved: 'no_usable_source', complete: false, saved: 0, new: 0, refreshed: 0, sources: [] }
    const said = 'No source gave a usable result, so nothing was imported and the job list was not changed.'
    expect(statusSentence(run({ status: 'failed', import: nothing }))).toBe(said)
    expect(ledgerText(run({ status: 'failed', import: nothing }))).toBe(said)
    expect(statusSentence(run({ status: 'skipped', import: nothing }))).toBe('Every source was skipped, so nothing was searched.')
    expect(ledgerText(run({ status: 'skipped', import: nothing }))).toBe(said)
    expect(statusSentence(run({ status: 'failed' }))).toBe('This run failed. The issues below say where.')
  })

  it('cancelled, interrupted and skipped each have a sentence', () => {
    expect(statusSentence(run({ status: 'cancelled', cancel: { requestedAt: null, outcome: 'collected_ads_saved', saved: 12 } }))).toBe('The last run was cancelled. 12 collected ads were saved. Nothing else changed. Scoring was skipped.')
    expect(statusSentence(run({ status: 'cancelled', cancel: { requestedAt: null, outcome: 'stopped_nothing_imported' } }))).toBe('The last run was cancelled. No ads were saved. Nothing else changed. Scoring was skipped.')
    expect(statusSentence(run({ status: 'interrupted', finishedAt: null }))).toMatch(/stopped without finishing.*not resumed/i)
    expect(statusSentence(run({ status: 'skipped' }))).toBe('Every source was skipped, so nothing was searched.')
    expect(statusSentence(run({ status: 'ok' }))).toBeNull()
  })

  it('an inferred interrupted run says the record and the lock disagree', () => {
    const inferred = answer([record(1, { status: 'running', finishedAt: null })], { alive: false }).runs[0]
    expect(inferred).toMatchObject({ status: 'interrupted', inferred: true })
    expect(statusSentence(inferred)).toMatch(/nothing is holding the run lock/)
  })

  it('a cancel that came after the commit is not called a cancelled run', () => {
    const late = run({ status: 'ok', cancel: { requestedAt: null, outcome: 'imported_before_cancel' } })
    expect(statusSentence(late)).toBe('The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped.')
    expect(statusLabel(late.status)).toBe('OK')
  })

  it('a source that had not finished is Unfinished, never Failed', () => {
    expect(sourceStatusLabel('unfinished')).toBe('Unfinished')
    expect(sourceStatusLabel('failed')).toBe('Failed')
    expect(sourceStatusLabel('nonsense')).toBe('Unknown')
  })

  it('an unfinished source does not look like a failed one', () => {
    expect(SOURCE_STATUS_TONES.unfinished).not.toBe(SOURCE_STATUS_TONES.failed)
    expect(SOURCE_NEW_NOTE).toMatch(/do not add up to the run's "New"/)
  })

  it('says what scoring did, and Not recorded when the record does not know', () => {
    expect(scoringText(run({}))).toBe('Finished')
    expect(scoringText(run({ steps: [{ name: 'discovery', status: 'ok' }], status: 'cancelled' }))).toBe('Skipped because the run was cancelled')
    expect(scoringText(run({ steps: [{ name: 'discovery', status: 'failed' }], status: 'failed' }))).toBe('Not run, because discovery did not finish')
    expect(scoringText(run({ steps: [] }))).toBe(NOT_RECORDED)
  })

  it('says how staging and the ledger fared', () => {
    expect(stagingText(run({}))).toBe('Saved correctly')
    expect(stagingText(run({ staging: { ok: false, problems: [] } }))).toMatch(/Staging failed/)
    expect(stagingText(run({ staging: undefined }))).toBe(NOT_RECORDED)
    expect(stagingText(run({ incompleteCommit: { runId: 'x' } }))).toMatch(/left incomplete/)
    expect(ledgerText(run({ import: importBlock() }))).toBe('1 closed, 2 marked absent, 0 reopened')
    expect(ledgerText(run({ import: importBlock({ kind: 'partial', ledger: undefined }) }))).toMatch(/^Nothing else changed/)
    expect(ledgerText(run({}))).toBe(NOT_RECORDED)
  })

  it('lists the biggest filter reasons and the rest as a count', () => {
    expect(filterReasonText({ title_not_matched: 400, location_not_matched: 22, country_not_matched: 3, not_listed: 1 })).toBe("Title didn't match: 400, Location didn't match: 22, Country didn't match: 3 and 1 more")
    expect(filterReasonText({ title_excluded: 5, made_up_reason: 2 })).toBe('Title had an excluded word: 5, Made up reason: 2')
    expect(filterReasonText({})).toBeNull()
    expect(filterReasonText(null)).toBe(NOT_RECORDED)
  })
})

describe('proof has three states and a text for every reason', () => {
  it('Proven, Not proven with reasons, and Not recorded', () => {
    expect(proofView({ state: 'proven', codes: ['proven'], boards: [] })).toMatchObject({ state: 'proven', label: 'Proven', lines: [table.proven.text] })
    expect(proofView({ state: 'not_proven', codes: ['source_failed', 'nothing_read'], boards: [] })).toMatchObject({ state: 'not_proven', label: 'Not proven', lines: [table.source_failed.text, table.nothing_read.text] })
    expect(proofView({ state: 'not_recorded', codes: [], boards: [] })).toEqual({ state: 'not_recorded', label: NOT_RECORDED, tone: 'low', lines: [] })
  })

  it('no data at all, or a state nobody named, is Not recorded and never Not proven', () => {
    for (const none of [undefined, null, {}, { state: 'not_recorded' }, { state: 'maybe', codes: ['source_failed'] }]) {
      expect(proofView(none)).toEqual({ state: 'not_recorded', label: NOT_RECORDED, tone: 'low', lines: [] })
    }
  })

  it('every code in the shared file has a text of its own, and that text is what is shown', () => {
    for (const [code, entry] of Object.entries(table)) {
      expect(entry.text.trim().length, code).toBeGreaterThan(10)
      expect(reasonText(code), code).toBe(entry.text)
    }
  })

  it('a code this build has no text for is shown as itself, never as nothing', () => {
    expect(reasonText('code_from_the_future')).toBe('Reason code: code_from_the_future')
    expect(proofView({ state: 'not_proven', codes: [], boards: [] }).lines).toEqual(['Not proven (the reason was not recorded)'])
  })
})
