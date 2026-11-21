// @vitest-environment jsdom
// The resume list follows the Jobs list's option A (owner decision 2026-11-21): tier, then the neutral order, the tier chip and no number.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountScreen, storedJob } from './setup/jobsScreenHarness.js'

vi.setConfig({ testTimeout: 60000, hookTimeout: 60000 })

const FILE = '../../../src/components/resumes/ResumeLibrary.jsx'
const withResume = (id, extra) => storedJob(id, { title: `Ad ${id}`, company: `Co ${id}`, tailoredAssets: { resumeMd: 'x.md', generatedAt: '2026-11-10T10:00:00Z' }, ...extra })

let screen
afterEach(async () => { await screen?.unmount(); screen = null })

const order = (container) => [...container.querySelectorAll('p.font-medium')].map((p) => p.textContent)

describe('the resume list', () => {
  it('orders by tier, then newest, then ad id: a higher score does not lift an ad inside its tier', async () => {
    screen = await mountScreen({
      file: FILE,
      props: { onNavigate() {} },
      stored: [
        withResume('weak', { matchScore: 30, datePosted: '2026-11-09' }),
        withResume('s-old-high', { matchScore: 99, datePosted: '2026-10-01' }),
        withResume('s-new-low', { matchScore: 71, datePosted: '2026-11-08' }),
        withResume('p', { matchScore: 60, datePosted: '2026-11-01' }),
      ],
    })
    expect(order(screen.container)).toEqual(['Co s-new-low', 'Co s-old-high', 'Co p', 'Co weak'])
  })

  it('shows the tier chip, the Engine not run marker on a provisional Strong fit, and no score number', async () => {
    screen = await mountScreen({
      file: FILE,
      props: { onNavigate() {} },
      stored: [
        withResume('a', { matchScore: 87, matchLabel: 'Excellent', engineCoverage: { status: 'not_evaluated', reason: 'no_answer' } }),
        withResume('b', { matchScore: 61, matchLabel: 'Good', engineCoverage: { status: 'answered' } }),
      ],
    })
    const text = screen.text()
    expect(text).toContain('Strong fit')
    expect(text).toContain('Engine not run')
    expect(text).toContain('Possible fit')
    expect(text).not.toMatch(/\b87\b|\b61\b/)
    expect(text).not.toContain('Excellent')
  })
})
