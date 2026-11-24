// The browser's own rows sent with a list request (src/modules/jobs/extraRows.js; docs/redesign/JOBS_LIST_SERVER_PLAN.md, P2b, a bridge removed in P5).
// What matters: an ALLOWLIST (private fields never pass, and the server refuses them if a client sends them), and a merge that changes only what it should.
import { describe, expect, it } from 'vitest'
import { MAX_JSON_BODY_BYTES } from '../../scripts/read-body.js'
import { EXTRA_ROW_FIELDS, EXTRA_TRACKING_FIELDS, ExtraRowsError, applyExtraRows, checkExtraRows, selectExtraRows } from '../../src/modules/jobs/extraRows.js'

const SECRET = 'PRIVATE-VALUE-7731'
/** Fields that are the owner's alone (manual-jobs rule: notes, links and source URL are in no payload) or too large or private to leave the browser. */
const PRIVATE_FIELDS = ['notes', 'extraLinks', 'sourceUrl', 'sourceChoice', 'outreach', 'tailoredAssets', 'aiInsights', 'llmFacts', 'engineShadow', 'keptRescoredAt', 'somethingNew']
const offList = (extra = {}) => ({ jobId: 'off1', title: 'Gone Ad', company: 'Acme', location: 'Remote', jobUrl: 'https://x.example/off1', offList: true, status: 'saved', matchScore: 60, ...extra })

const deepFreeze = (value) => {
  if (value && typeof value === 'object') { Object.values(value).forEach(deepFreeze); Object.freeze(value) }
  return value
}

describe('what leaves the browser is an allowlist', () => {
  it('the allowlist names none of the owner\'s private fields', () => {
    for (const field of PRIVATE_FIELDS) expect(EXTRA_ROW_FIELDS).not.toContain(field)
    expect(EXTRA_TRACKING_FIELDS).toEqual(['applied', 'interviewStage', 'followUpDate'])
  })

  it.each(PRIVATE_FIELDS)('%s never passes, on a browser-only row or on a row the server holds', (field) => {
    const sent = selectExtraRows([offList({ [field]: SECRET }), { jobId: 'held1', title: 'Held', status: 'saved', [field]: SECRET }])
    expect(JSON.stringify(sent)).not.toContain(SECRET)
    expect(sent).toHaveLength(2)
  })

  it('a tracking object leaves as three values; its notes, contacts and addresses stay', () => {
    const tracking = { applied: true, interviewStage: 'Interview', followUpDate: '2026-12-01', notes: SECRET, recruiterName: SECRET, recruiterEmail: SECRET, recruiterLinkedIn: SECRET, applicationUrl: SECRET }
    const sent = selectExtraRows([{ jobId: 'held1', title: 'Held', applicationTracking: tracking }, offList({ applicationTracking: tracking })])
    expect(JSON.stringify(sent)).not.toContain(SECRET)
    for (const row of sent) expect(row.applicationTracking).toEqual({ applied: true, interviewStage: 'Interview', followUpDate: '2026-12-01' })
  })

  it('the owner\'s work on a row is one flag, never its content', () => {
    const sent = selectExtraRows([
      { jobId: 'a', title: 'A', outreach: { status: 'sent', contacts: [{ name: SECRET, email: SECRET }] } },
      { jobId: 'b', title: 'B', tailoredAssets: { resumeMd: SECRET } },
      { jobId: 'c', title: 'C', aiInsights: { summary: SECRET } },
      { jobId: 'd', title: 'D' },
    ])
    expect(JSON.stringify(sent)).not.toContain(SECRET)
    expect(sent.map((row) => [row.jobId, row.ownerWork])).toEqual([['a', true], ['b', true], ['c', true]])
  })

  it('a row only the browser has goes in full; a row the server has goes as its owner state alone; an unworked row does not go', () => {
    const sent = selectExtraRows([
      offList(),
      { jobId: 'man1', manualEntry: true, title: 'Mine', company: 'Me', jobUrl: 'https://y.example/1', description: 'text', notes: SECRET },
      { jobId: 'held1', title: 'Held on the server', company: 'Acme', status: 'saved', keptByUser: true },
      { jobId: 'plain1', title: 'Plain', status: 'new' },
    ])
    expect(sent.map((row) => row.jobId)).toEqual(['off1', 'man1', 'held1'])
    expect(sent[0]).toMatchObject({ title: 'Gone Ad', offList: true, status: 'saved', ownerWork: true })
    expect(sent[1]).toMatchObject({ title: 'Mine' })
    expect(sent[2]).toEqual({ jobId: 'held1', status: 'saved', keptByUser: true, ownerWork: true }) // no title, company or text: the server's stand
  })
})

describe('rows are slim, so the request cap is hard to reach', () => {
  const long = 'x'.repeat(9500) // the ad text of a typical row: 9.5 KB on the real scored rows
  const rows = Array.from({ length: 600 }, (_, i) => offList({ jobId: `off${i}`, description: long, jobUrl: `https://x.example/${i}` }))

  it('the ad\'s text is not sent unless a text search is on', () => {
    expect(selectExtraRows([offList({ description: long })]).every((row) => !('description' in row))).toBe(true)
    expect(selectExtraRows([offList({ description: long })], { withText: true })[0].description).toBe(long)
  })

  it('600 browser-only rows with long ads fit one request by a wide margin; with a search on they do not, and that is an error to show', () => {
    expect(JSON.stringify({ extraRows: selectExtraRows(rows) }).length).toBeLessThan(MAX_JSON_BODY_BYTES / 2)
    expect(JSON.stringify({ extraRows: selectExtraRows(rows, { withText: true }) }).length).toBeGreaterThan(MAX_JSON_BODY_BYTES)
  })
})

describe('the server refuses what is not on the allowlist', () => {
  it.each(PRIVATE_FIELDS)('a row with %s is refused, and the message never quotes a value', (field) => {
    expect(() => checkExtraRows([{ jobId: 'x1', [field]: SECRET }])).toThrow(ExtraRowsError)
    try { checkExtraRows([{ jobId: 'x1', [field]: SECRET }]) } catch (error) {
      expect(error.message).toContain('extraRows[0]')
      expect(error.message).not.toContain(SECRET)
    }
  })

  it('a tracking field outside the three is refused', () => {
    expect(() => checkExtraRows([{ jobId: 'x1', applicationTracking: { applied: true, notes: SECRET } }])).toThrow(/applicationTracking has a field that is not allowed/)
  })

  it.each([
    ['not a list', { jobId: 'x1' }],
    ['a row that is not an object', ['x1']],
    ['no jobId', [{ title: 'No id' }]],
    ['a jobId with a path in it', [{ jobId: '../x' }]],
    ['a repeated jobId', [{ jobId: 'x1' }, { jobId: 'x1' }]],
    ['ownerWork that is not true', [{ jobId: 'x1', ownerWork: 'yes' }]],
  ])('refuses %s', (_name, rows) => {
    expect(() => checkExtraRows(rows)).toThrow(ExtraRowsError)
  })

  it('takes what the browser builds, and nothing as nothing', () => {
    const rows = selectExtraRows([offList(), { jobId: 'held1', status: 'saved' }])
    expect(checkExtraRows(rows)).toBe(rows)
    expect(checkExtraRows(undefined)).toEqual([])
    expect(checkExtraRows(null)).toEqual([])
  })
})

describe('putting the browser\'s rows into the server\'s for one request', () => {
  const held = { jobId: 'held1', title: 'Server title', company: 'Server Co', jobUrl: 'https://s.example/1', status: 'new', matchScore: 70 }

  it('a row the server holds keeps its ad fields and takes only the owner\'s state', () => {
    const out = applyExtraRows([held], [{ jobId: 'held1', status: 'saved', keptByUser: true, ownerWork: true, applicationTracking: { applied: true } }])
    expect(out).toEqual([{ ...held, status: 'saved', keptByUser: true, ownerWork: true, applicationTracking: { applied: true } }])
    // an extra row cannot rewrite an ad field of a row the server holds, even if a client sent one
    const tampered = applyExtraRows([held], [{ jobId: 'held1', title: 'Local title', matchScore: 99, ownerWork: true }])
    expect(tampered[0]).toMatchObject({ title: 'Server title', matchScore: 70, ownerWork: true })
  })

  it('finds a row the server holds by its address when the id differs', () => {
    const out = applyExtraRows([held], [{ jobId: 'other-id', jobUrl: 'https://s.example/1', title: 'Server title', status: 'rejected', ownerWork: true }])
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ jobId: 'held1', status: 'rejected' })
  })

  it('a row the server does not hold is added as it was sent', () => {
    const out = applyExtraRows([held], [offList()])
    expect(out.map((row) => row.jobId)).toEqual(['held1', 'off1'])
    expect(out[1]).toMatchObject({ offList: true, title: 'Gone Ad' })
  })

  it('a hand-entered job drops a server row with its address under another id, as an import does', () => {
    const discovered = { jobId: 'disc1', title: 'Same posting', jobUrl: 'https://y.example/1' }
    const out = applyExtraRows([held, discovered], [{ jobId: 'man1', manualEntry: true, title: 'Mine', jobUrl: 'https://y.example/1' }])
    expect(out.map((row) => row.jobId)).toEqual(['held1', 'man1'])
  })

  it('changes none of its inputs, and an empty list gives the list itself', () => {
    const stored = deepFreeze([held])
    const extra = deepFreeze([{ jobId: 'held1', status: 'saved', ownerWork: true }, offList()])
    expect(() => applyExtraRows(stored, extra)).not.toThrow()
    expect(applyExtraRows(stored, [])).toBe(stored)
  })
})
