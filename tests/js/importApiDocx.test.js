import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../src/utils/apiAvailability.js', () => ({ ensureApiAvailable: async () => true }))
const { DOCX_MIME, parseDocxFile } = await import('../../src/modules/profile/importApi.js')

afterEach(() => vi.unstubAllGlobals())
const file = (size = 100) => ({ name: 'jane-sample.docx', size })

describe('parseDocxFile', () => {
  it('posts the file itself with the Word content type and returns the draft; the file name is not sent', async () => {
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, draft: { source: 'resume_docx' } }) }))
    vi.stubGlobal('fetch', fetchFn)
    const f = file()
    expect(await parseDocxFile(f)).toEqual({ source: 'resume_docx' })
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/profile/import/parse-docx')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': DOCX_MIME })
    expect(init.body).toBe(f)
    expect(JSON.stringify([url, init.method, init.headers])).not.toContain('jane-sample') // the name is neither in the address nor in a header
  })

  it('refuses an oversized file before sending', async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal('fetch', fetchFn)
    await expect(parseDocxFile(file(11 * 1024 * 1024))).rejects.toThrow(/too large/)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("shows the server's fixed message on a refusal, and a generic one when the answer is not JSON", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ ok: false, error: 'The file is password protected.' }) })))
    await expect(parseDocxFile(file())).rejects.toThrow('The file is password protected.')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => { throw new Error('html') } })))
    await expect(parseDocxFile(file())).rejects.toThrow('The file could not be read.')
  })
})
