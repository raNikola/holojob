// The two number settings of Settings > Sources (list-cleanup 2c): what is sent, what is refused before sending, and that the route carries them to the
// code that reads them. The bounds themselves are the server's (tests/python/test_source_settings.py).
import http from 'node:http'
import { describe, expect, it } from 'vitest'
import { numbersChanges, numbersDraftFrom } from '../../src/modules/sources/numberSettings.js'
import { saveSourceNumbers } from '../../src/modules/sources/sourcesClient.js'
import { handleSourcesRequest, setSourcesRunner } from '../../scripts/sources-handler.js'

const SERVER = { descriptionRetry: { maxTotal: 2, perScan: 1 }, repostWindowDays: 90, limits: { retryMax: 10, retryDefault: 2, repostWindowMax: 365, repostWindowDefault: 90 } }

describe('the draft and what it sends', () => {
  it('starts from the server values and sends nothing while nothing changed', () => {
    const draft = numbersDraftFrom(SERVER)
    expect(draft).toEqual({ maxTotal: '2', repostWindowDays: '90' })
    expect(numbersChanges(draft, SERVER)).toEqual({ payload: null, errors: {} })
  })

  it('sends only the field that changed', () => {
    expect(numbersChanges({ maxTotal: '2', repostWindowDays: '30' }, SERVER).payload).toEqual({ repostWindowDays: 30 })
    expect(numbersChanges({ maxTotal: '0', repostWindowDays: '90' }, SERVER).payload).toEqual({ descriptionRetry: { maxTotal: 0 } })
  })

  it.each([['11', '90', 'maxTotal'], ['-1', '90', 'maxTotal'], ['x', '90', 'maxTotal'], ['2', '0', 'repostWindowDays'], ['2', '366', 'repostWindowDays'], ['2', '1.5', 'repostWindowDays']])(
    'refuses %s / %s before sending', (maxTotal, days, field) => {
      const { payload, errors } = numbersChanges({ maxTotal, repostWindowDays: days }, SERVER)
      expect(payload).toBeNull()
      expect(Object.keys(errors)).toEqual([field])
    })
})

describe('the route carries both numbers on', () => {
  it('passes them to the settings code with no boards, and still never a consent time', async () => {
    const calls = []
    setSourcesRunner(async (command, input) => { calls.push({ command, input }); return { ok: true } })
    const server = http.createServer(async (req, res) => { if (!(await handleSourcesRequest(req, res))) res.end('{}') })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    try {
      const base = `http://127.0.0.1:${server.address().port}`
      const fetchImpl = (path, init) => fetch(base + path, init)
      const result = await saveSourceNumbers({ descriptionRetry: { maxTotal: 3 }, repostWindowDays: 60, consentAcceptedAt: '1999' }, fetchImpl)
      expect(result.ok).toBe(true)
    } finally {
      setSourcesRunner()
      await new Promise((r) => server.close(r))
    }
    expect(calls).toEqual([{ command: 'put', input: { descriptionRetry: { maxTotal: 3 }, repostWindowDays: 60 } }])
  })
})
