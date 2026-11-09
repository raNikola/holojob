// What the owner sees when tailoring did not use the AI draft, or the documents state facts the profile does not.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../src/context/ProfileContext', () => ({ useProfile: () => ({ profile: {} }) }))

const { default: JobTailorActions } = await import('../../src/components/jobs/JobTailorActions.jsx')

const render = (tailoredAssets) => renderToStaticMarkup(
  createElement(JobTailorActions, { job: { jobId: 'j1', title: 'T', company: 'C', tailoredAssets }, apiAvailable: true }),
)

describe('tailoring reasons are shown', () => {
  it('lists why the AI draft was rejected', () => {
    const html = render({ llmIssues: ['llm output rejected, fell back to rule-based: Unverified number: 47'], provenancePassed: true })
    expect(html).toContain('tailor-llm-issues')
    expect(html).toContain('Unverified number: 47')
    expect(html).not.toContain('tailor-provenance-issues')
  })

  it('lists the unverified claims of finished documents', () => {
    const html = render({ llmIssues: [], provenancePassed: false, provenanceIssues: ['Unverified number: 9'] })
    expect(html).toContain('tailor-provenance-issues')
    expect(html).toContain('Unverified number: 9')
  })

  it('shows nothing extra when all is well', () => {
    const html = render({ llmIssues: [], provenancePassed: true, provenanceIssues: [] })
    expect(html).not.toContain('tailor-llm-issues')
    expect(html).not.toContain('tailor-provenance-issues')
  })
})
