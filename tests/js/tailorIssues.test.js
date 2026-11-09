// What the owner sees when tailoring did not use the AI draft, or the documents state facts the profile does not.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { CHECKS_FAILED, CHECKS_PASSED, CHECK_LIMITS, NOT_COVERED } from '../../src/modules/jobs/factCheckNote.js'

vi.mock('../../src/context/ProfileContext', () => ({ useProfile: () => ({ profile: {} }) }))

const { default: JobTailorActions } = await import('../../src/components/jobs/JobTailorActions.jsx')

const render = (tailoredAssets) => renderToStaticMarkup(
  createElement(JobTailorActions, { job: { jobId: 'j1', title: 'T', company: 'C', tailoredAssets }, apiAvailable: true }),
)

describe('tailoring reasons are shown', () => {
  it('lists why the AI draft was rejected', () => {
    const html = render({ llmIssues: ['The AI text was rejected and rule-based text was used: Unverified number: 47'], provenancePassed: true })
    expect(html).toContain('tailor-llm-issues')
    expect(html).toContain('Unverified number: 47')
    expect(html).not.toContain('tailor-provenance-issues')
  })

  it('lists the unverified claims of finished documents', () => {
    const html = render({ llmIssues: [], provenancePassed: false, provenanceIssues: ['Unverified number: 9'] })
    expect(html).toContain('tailor-provenance-issues')
    expect(html).toContain('Unverified number: 9')
  })

  it('shows no failure notice when all is well', () => {
    const html = render({ llmIssues: [], provenancePassed: true, provenanceIssues: [] })
    expect(html).not.toContain('tailor-llm-issues')
    expect(html).not.toContain('tailor-provenance-issues')
  })

  it('words a pass as "passed the automatic checks", never as a guarantee, and lists what is not checked', () => {
    const html = render({ llmIssues: [], provenancePassed: true, provenanceIssues: [] })
    expect(html).toContain('tailor-checks-passed')
    expect(html).toContain(CHECKS_PASSED)
    expect(html).toContain('Read it before you send it')
    for (const gap of NOT_COVERED) expect(html).toContain(gap)
    expect(html.toLowerCase()).not.toMatch(/guarantee|all facts are true|verified true|fully verified|fact-?checked/)
  })

  it('words a failure as "did not pass the automatic checks"', () => {
    const html = render({ llmIssues: [], provenancePassed: false, provenanceIssues: ['Unverified number: 9'] })
    expect(html).toContain(CHECKS_FAILED)
    expect(html).not.toContain('tailor-checks-passed')
  })

  it('names the four uncovered cases the owner asked for', () => {
    expect(CHECK_LIMITS).toMatch(/lowercase/)
    expect(CHECK_LIMITS).toMatch(/reworded into a false one/)
    expect(CHECK_LIMITS).toMatch(/reused with another meaning/)
    expect(CHECK_LIMITS).toMatch(/tone/)
    expect(CHECK_LIMITS).toMatch(/do not prove every statement is true/)
  })
})
