// @vitest-environment jsdom
// The AI cover letter is a draft: the download appears only after the server accepts it, and a refusal shows why.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('../../src/utils/apiAvailability', () => ({ ensureApiAvailable: async () => true, isApiAvailable: () => true }))

const { default: CoverLetterAccept } = await import('../../src/components/ai/CoverLetterAccept.jsx')

let host
let root
afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  vi.unstubAllGlobals()
})

async function mount() {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () => { root.render(createElement(CoverLetterAccept, { jobId: 'job-1' })) })
}
const click = async () => { await act(async () => { host.querySelector('[data-testid="cover-letter-accept"]').click() }); await act(async () => { await Promise.resolve() }) }

describe('CoverLetterAccept', () => {
  it('offers no download before the server accepts the draft', async () => {
    await mount()
    expect(host.querySelector('[data-testid="cover-letter-download"]')).toBeNull()
    expect(host.textContent).toContain('This is a draft')
    expect(host.textContent).toContain('not a guarantee')
  })

  it('posts the job id and the confirmation only, then offers the document', async () => {
    const fetchStub = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, passed: true }) }))
    vi.stubGlobal('fetch', fetchStub)
    await mount()
    await click()
    const [url, init] = fetchStub.mock.calls[0]
    expect(url).toBe('/api/ai/cover-letter/accept')
    expect(JSON.parse(init.body)).toEqual({ jobId: 'job-1', confirm: true })
    expect(host.querySelector('[data-testid="cover-letter-download"]').getAttribute('href')).toBe('/api/resumes/job-1/ai_cover_letter.md')
    expect(host.textContent).toContain('Passed the automatic checks')
    expect(host.querySelector('[data-testid="cover-letter-limits"]').textContent).toContain('do not prove every statement is true')
  })

  it('shows the refusal and the unverified claims, and still offers no download', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ ok: false, message: 'The letter states facts the profile does not.', issues: ['Unverified number: 47'] }) })))
    await mount()
    await click()
    expect(host.querySelector('[data-testid="cover-letter-refused"]').textContent).toContain('Unverified number: 47')
    expect(host.querySelector('[data-testid="cover-letter-download"]')).toBeNull()
  })
})
