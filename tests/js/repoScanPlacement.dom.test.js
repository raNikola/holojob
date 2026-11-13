// @vitest-environment jsdom
// The repo scan lives in the Repos step; the questionnaire only points to it and counts confirmed answers.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let mockProfile
vi.mock('../../src/context/ProfileContext', () => ({
  useProfile: () => ({ profile: mockProfile, updateProfile: vi.fn() }),
}))
vi.mock('../../src/modules/jobs/profileSync', () => ({ saveProfileToDataDir: vi.fn() }))
vi.mock('../../src/utils/apiAvailability', () => ({ ensureApiAvailable: async () => true }))

const { default: RepositoryForm } = await import('../../src/components/repositories/RepositoryForm.jsx')
const { default: QuestionnaireForm } = await import('../../src/components/questionnaire/QuestionnaireForm.jsx')
const { derivedEntry } = await import('../../src/modules/profile/questionnaireStatus.js')

const makeProfile = (repositories, answers = []) => ({
  repositories,
  resume: { parsedData: { skills: [] } },
  questionnaire: { answers },
})

let root
let host
const mount = async (el, intel = null) => {
  vi.stubGlobal('fetch', vi.fn(async (url) => ({
    ok: true,
    json: async () => (String(url).includes('projects/intelligence') ? intel : null),
  })))
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () => { root.render(el) })
  await act(async () => {})
}
afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  vi.unstubAllGlobals()
})
const scanButton = () => [...host.querySelectorAll('button')].find((b) => /Scan GitHub repos|Re-scan repos/.test(b.textContent))

describe('Scan GitHub repos', () => {
  it('is in the Repos step and disabled without any link or path', async () => {
    mockProfile = makeProfile({ githubLinks: [''], localRepoPaths: [] })
    await mount(createElement(RepositoryForm))
    expect(scanButton().disabled).toBe(true)
  })

  it('is enabled with a GitHub link, and shows last scan only from saved data', async () => {
    mockProfile = makeProfile({ githubLinks: ['https://github.com/x'], localRepoPaths: [] })
    await mount(createElement(RepositoryForm))
    expect(scanButton().disabled).toBe(false)
    expect(host.textContent).not.toContain('Last scan')
  })

  it('shows the saved repo count and re-scan label', async () => {
    mockProfile = makeProfile({ githubLinks: [], localRepoPaths: ['/p'] })
    await mount(createElement(RepositoryForm), { projects: [{ name: 'a' }, { name: 'b' }] })
    expect(scanButton().textContent).toContain('Re-scan repos')
    expect(host.textContent).toContain('Last scan: 2 repo(s)')
  })

  it('is gone from the questionnaire, which shows one line when repos exist and none was scanned', async () => {
    mockProfile = makeProfile({ githubLinks: ['https://github.com/x'], localRepoPaths: [] })
    await mount(createElement(QuestionnaireForm, { questionIndex: 0 }))
    expect(scanButton()).toBeUndefined()
    expect(host.textContent).toContain('Scan your repos in the Repos step to pre-fill skills.')
  })
})

describe('questionnaire counter', () => {
  it('counts only confirmed answers and drops the number prefix from the question title', async () => {
    mockProfile = makeProfile({ githubLinks: [], localRepoPaths: [] }, [
      { id: 1, question: 'Q1', answer: 'x' },
      derivedEntry(2, 'Q2', 'A; B'),
    ])
    await mount(createElement(QuestionnaireForm, { questionIndex: 0 }))
    expect(host.textContent).toContain('1/17 answered')
    expect(host.textContent).not.toMatch(/\b\d+\. /)
  })
})
