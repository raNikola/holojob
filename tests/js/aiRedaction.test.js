import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { RedactionError, assertClean, redactText, setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { buildAiContext, buildAiRedactionHints } from '../../src/modules/ai/aiContextBuilder.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'

// Fake people: nothing here is real.
const OWNER = {
  name: 'Zlatan Qwerty', email: 'zlatan.qwerty@owner-test.example', phone: '+381 64 555 0199',
  site: 'https://qwerty-cv.example/zlatan', linkedin: 'https://www.linkedin.com/in/zlatan-qwerty', github: 'https://github.com/zqwerty/taskflow',
}
const RECRUITER = {
  name: 'Mirela Fakeson', email: 'mirela.fakeson@recruit-test.example', linkedin: 'https://www.linkedin.com/in/mirela-fakeson',
  phone: '+49 170 5550123',
}
const COMPANY_EMAIL = 'hr@acme-test.example'

const SECRETS = [
  'Zlatan', 'Qwerty', 'zlatan.qwerty', 'owner-test.example', '555 0199', '5550199', 'qwerty-cv.example', 'zlatan-qwerty', 'zqwerty',
  'Mirela', 'Fakeson', 'mirela.fakeson', 'recruit-test.example', 'mirela-fakeson', '170 5550123', COMPANY_EMAIL,
]

const FEATURES = ['jobAnalysis', 'resumeEnhancement', 'coverLetter', 'interviewPrep', 'outreach', 'companyIntelligence',
  'careerStrategy', 'skillGap', 'applicationStrategy', 'chat']

const JOB = {
  jobId: 'wk-12345678901',
  title: 'Senior Product Manager',
  company: 'Acme',
  location: 'Remote',
  matchScore: 81,
  postedAt: '2026-10-20',
  description: `<p>Own the roadmap. Salary 80000-120000 EUR. Apply to ${COMPANY_EMAIL}, recruiter ${RECRUITER.name}
    (${RECRUITER.email}, ${RECRUITER.linkedin}, call ${RECRUITER.phone}). Candidate ${OWNER.name} wrote from ${OWNER.site}.
    Company site https://acme.example/careers.</p>`,
  applicationTracking: {
    applied: true, interviewStage: 'HR Screen', recruiterName: RECRUITER.name, recruiterEmail: RECRUITER.email,
    recruiterLinkedIn: RECRUITER.linkedin, notes: `spoke with ${RECRUITER.name}`, applicationUrl: 'https://acme.example/apply/9',
  },
  outreach: {
    status: 'sent',
    contacts: [{ id: 'c1', name: RECRUITER.name, email: RECRUITER.email, linkedinUrl: RECRUITER.linkedin, title: 'Recruiter', company: 'Acme', contactType: 'recruiter' }],
    activity: [{ date: '2026-10-21', type: 'contact_added', notes: `Added ${RECRUITER.name}` }],
  },
}

const PROFILE = {
  basicProfile: { fullName: OWNER.name, email: OWNER.email, phone: OWNER.phone, currentRole: 'Product Manager', linkedinUrl: OWNER.linkedin },
  resume: { parsedData: { skills: ['Roadmapping'], links: [OWNER.site] } },
  repositories: { githubLinks: [OWNER.github] },
}

function installStorage() {
  const data = new Map([
    ['job-dashboard-candidate-profile', JSON.stringify({ ...PROFILE, completion: {} })],
    ['job-dashboard-discovered-jobs', JSON.stringify({ jobs: [JOB] })],
    ['job-dashboard-candidate-intelligence', JSON.stringify({ candidateSummary: { headline: 'PM' }, roleStrategy: { primaryRoles: ['PM'] } })],
  ])
  globalThis.localStorage = {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  }
}

/** The context exactly as aiClient.js sends it. */
function browserContext(featureId) {
  const extra = featureId === 'outreach' ? { contact: JOB.outreach.contacts[0], messageType: 'inmail', outreach: JOB.outreach } : undefined
  const job = ['skillGap', 'applicationStrategy', 'careerStrategy', 'chat'].includes(featureId) ? undefined : JOB
  const context = buildAiContext({ featureId, job, message: `Write to ${RECRUITER.name} at ${RECRUITER.email} from ${OWNER.email}`, extra })
  return { ...context, redactionHints: buildAiRedactionHints({ job, extra }) }
}

let sent
let gateCalls

// The key comes from the server's secret store; the apiKey: 'k' these calls still carry must be ignored.
useTempSecretStore()

beforeEach(() => {
  setAiSecret('openai', { key: CANARY })
  installStorage()
  sent = []
  gateCalls = []
  setGateRunner(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? { allowed: true, id: 'c1' } : { ok: true }
  })
  for (const name of ['openai', 'mock']) {
    vi.spyOn(getProvider(name), 'complete').mockImplementation(async ({ messages }) => {
      sent.push(messages)
      return { text: '{"answer":"ok"}', usage: {} }
    })
  }
})

afterEach(() => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
  delete globalThis.localStorage
})

const promptOf = (messages) => messages.map((m) => m.content).join('\n')
const disk = () => ({ names: [OWNER.name], emails: [OWNER.email], phones: [OWNER.phone], links: [OWNER.site, OWNER.linkedin, OWNER.github] })

describe('every browser AI feature sends no identifiers to the provider', () => {
  for (const feature of FEATURES) {
    it(`${feature}: nothing identifying reaches the provider (hints + profile mirror)`, async () => {
      setIdentitySource(disk)
      const result = await runAiFeature({ feature, context: browserContext(feature), settings: { provider: 'openai', apiKey: 'k' } })
      expect(result.refused).toBeUndefined()
      expect(sent).toHaveLength(1)
      const prompt = promptOf(sent[0])
      for (const secret of SECRETS) expect(prompt, `${feature} leaked ${secret}`).not.toContain(secret)
      expect(prompt).not.toMatch(/@/)
      expect(prompt).not.toMatch(/linkedin\.com|github\.com/i)
    })
  }

  it('also holds with only the browser hints (no profile mirror on disk) and for the mock provider', async () => {
    setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
    for (const provider of ['openai', 'mock']) {
      sent = []
      await runAiFeature({ feature: 'jobAnalysis', context: browserContext('jobAnalysis'), settings: { provider, apiKey: 'k' } })
      for (const secret of SECRETS) expect(promptOf(sent[0])).not.toContain(secret)
    }
  })

  it('also holds with only the profile mirror (no hints) for the owner, and still removes any e-mail', async () => {
    setIdentitySource(disk)
    const { redactionHints, ...bare } = browserContext('chat')
    expect(redactionHints).toBeTruthy()
    await runAiFeature({ feature: 'chat', context: { ...bare, message: `${OWNER.name} ${OWNER.email} ${OWNER.phone} ${RECRUITER.email}` }, settings: { provider: 'openai', apiKey: 'k' } })
    const prompt = promptOf(sent[0])
    for (const secret of [...SECRETS.slice(0, 8), RECRUITER.email]) expect(prompt).not.toContain(secret)
  })

  it('the hints themselves are not sent', async () => {
    setIdentitySource(disk)
    await runAiFeature({ feature: 'jobAnalysis', context: browserContext('jobAnalysis'), settings: { provider: 'openai', apiKey: 'k' } })
    expect(promptOf(sent[0])).not.toContain('redactionHints')
  })

  it('keeps what the model needs: title, company, salary range, dates, ids, a company site', async () => {
    setIdentitySource(disk)
    await runAiFeature({ feature: 'jobAnalysis', context: browserContext('jobAnalysis'), settings: { provider: 'openai', apiKey: 'k' } })
    const prompt = promptOf(sent[0])
    for (const keep of ['Senior Product Manager', 'Acme', '80000-120000', 'wk-12345678901', 'https://acme.example/careers', 'HR Screen']) {
      expect(prompt).toContain(keep)
    }
  })

  it('the context builder already leaves the contact fields out, before any redaction', () => {
    // The job's free-text description is left to the server-side redaction; everything structured is already clean.
    const { redactionHints: _hints, ...rest } = browserContext('outreach')
    const json = JSON.stringify({ ...rest, job: { ...rest.job, description: '' } })
    for (const secret of [OWNER.name, OWNER.email, RECRUITER.name, RECRUITER.email, RECRUITER.linkedin, 'spoke with', 'acme.example/apply']) {
      expect(json).not.toContain(secret)
    }
    expect(JSON.stringify(browserContext('outreach').contact)).toContain('[CONTACT NAME]')
  })
})

describe('fail closed', () => {
  it('refuses and logs the refusal when the redaction step cannot run; the provider is never called', async () => {
    setIdentitySource(() => { throw new RedactionError('profile mirror unreadable (candidate-profile.json): cannot tell what to redact') })
    const result = await runAiFeature({ feature: 'jobAnalysis', context: browserContext('jobAnalysis'), settings: { provider: 'openai', apiKey: 'k' } })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(result.error).toContain('call not made')
    expect(getProvider('openai').complete).not.toHaveBeenCalled()
    expect(gateCalls.map((c) => c.command)).toEqual(['refuse'])
    expect(gateCalls[0].input).toMatchObject({ provider: 'openai', feature: 'jobAnalysis' })
    expect(JSON.stringify(gateCalls)).not.toContain(OWNER.email)
  })

  it('treats an unexpected error inside redaction the same way', async () => {
    setIdentitySource(() => { throw new TypeError('boom') })
    const result = await runAiFeature({ feature: 'chat', context: { message: 'hi' }, settings: { provider: 'openai', apiKey: 'k' } })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(getProvider('openai').complete).not.toHaveBeenCalled()
  })

  it('a refused mock call is not recorded (the mock is not a model call) but is still refused', async () => {
    setIdentitySource(() => { throw new RedactionError('x') })
    const result = await runAiFeature({ feature: 'chat', context: { message: 'hi' }, settings: { provider: 'mock' } })
    expect(result.refused).toBe(true)
    expect(gateCalls).toEqual([])
  })

  it('redaction runs before the budget gate: the gate sees the redacted prompt size and never a secret', async () => {
    setIdentitySource(disk)
    await runAiFeature({ feature: 'jobAnalysis', context: browserContext('jobAnalysis'), settings: { provider: 'openai', apiKey: 'k' } })
    expect(gateCalls[0].command).toBe('reserve')
    expect(gateCalls[0].input.promptChars).toBe(sent[0].reduce((n, m) => n + m.content.length, 0))
    expect(JSON.stringify(gateCalls)).not.toContain(OWNER.email)
  })

  it('the last check refuses a prompt that still holds an identifier', () => {
    const ids = { owner: { names: [OWNER.name], emails: [], phones: [], links: [] }, contacts: { names: [], emails: [], phones: [], links: [] } }
    expect(() => assertClean([{ role: 'user', content: 'mail me at someone@x.example' }], ids)).toThrow(/email/)
    expect(() => assertClean([{ role: 'user', content: 'see linkedin.com/in/someone' }], ids)).toThrow(/profile link/)
    expect(() => assertClean([{ role: 'user', content: 'Zlatan' }], ids)).toThrow(/name/)
    expect(() => assertClean([{ role: 'user', content: 'call +49 170 5550123' }], ids)).toThrow(/phone/)
    expect(() => assertClean([{ role: 'user', content: 'Senior PM, 80000-120000 EUR, 2026-10-20, v1.2.3' }], ids)).not.toThrow()
  })
})

describe('documented rules', () => {
  const none = { names: [], emails: [], phones: [], links: [] }
  const ids = { owner: none, contacts: none }

  it('a company e-mail in job text is replaced like any other e-mail', () => {
    expect(redactText(`Send CVs to ${COMPANY_EMAIL} today`, ids)).toBe('Send CVs to [EMAIL] today')
  })

  it('profile-site links go, a company site stays', () => {
    expect(redactText('see https://github.com/someone and rs.linkedin.com/in/x and https://acme.example/jobs', ids))
      .toBe('see [LINK] and [LINK] and https://acme.example/jobs')
  })

  it('phone-like numbers go; ranges, dates, decimals and plain ids stay', () => {
    expect(redactText('call +381 64 123 4567 or 064/123-4567', ids)).toBe('call [PHONE] or [PHONE]')
    for (const keep of ['100 000 - 120 000 EUR', '29.10.2026', '0.123456789', '2019-2024', 'id 12345678901']) {
      expect(redactText(keep, ids)).toBe(keep)
    }
  })

  it('names match without accents and as whole words only', () => {
    const named = { owner: { ...none, names: ['Đorđe Marković'] }, contacts: none }
    expect(redactText('Djordje Markovic and Markovicz, Markovic', named)).toBe('[NAME] and Markovicz, [NAME]')
  })
})
