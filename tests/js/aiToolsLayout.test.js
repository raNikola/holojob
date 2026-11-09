// The job's document actions live inside the one "AI Tools" section, above the AI tabs; nowhere else, and nothing is lost.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../src/context/ProfileContext', () => ({ useProfile: () => ({ profile: {} }) }))
vi.mock('../../src/components/jobs/ApplicationTrackerPanel', () => ({ default: () => null }))
vi.mock('../../src/components/outreach/RelatedContactsPanel', () => ({ default: () => null }))

const { default: JobDetailBody } = await import('../../src/components/jobs/JobDetailBody.jsx')

const JOB = {
  jobId: 'j1', title: 'Lead PM', company: 'Hiring Co', matchScore: 80, priority: 'P1', applyRecommendation: 'Apply', status: 'new',
  tailoredAssets: { resumeMd: 'data/resumes/j1/tailored_resume.md', provenancePassed: true, provenanceIssues: [], llmIssues: [] },
}
const render = (props = {}, job = JOB) => renderToStaticMarkup(createElement(JobDetailBody, { job, apiAvailable: true, onJobUpdated() {}, onStatusChange() {}, includeTracker: false, includeContacts: false, ...props }))
const count = (html, text) => html.split(text).length - 1

describe('one AI Tools section', () => {
  it('details page: the documents sit at the top of the section, above the AI tabs, under one heading', () => {
    const html = render()
    expect(count(html, '>AI Tools<')).toBe(1)
    expect(count(html, 'data-testid="ai-tools-section"')).toBe(1)
    expect(html.indexOf('data-testid="ai-tools-documents"')).toBeGreaterThan(html.indexOf('>AI Tools<'))
    expect(html.indexOf('Documents</h4>')).toBeLessThan(html.indexOf('Analysis'))
    expect(html.indexOf('tailor-checks-passed')).toBeLessThan(html.indexOf('Analysis'))
    expect(html.toLowerCase()).not.toContain('tailor ')
  })

  it('drawer (no AI tabs): the same section and heading hold the document actions alone', () => {
    const html = render({ includeAiTools: false })
    expect(count(html, '>AI Tools<')).toBe(1)
    expect(html).toContain('data-testid="ai-tools-documents"')
    expect(html).toContain('tailor-checks-passed')
    expect(html).not.toContain('Analysis')
    expect(html).not.toContain('Cover Letter')
  })

  it('read-only details (no documents, no AI tools): no section at all', () => {
    const html = render({ includeTailor: false, includeAiTools: false })
    expect(html).not.toContain('AI Tools')
  })

  it('AI tabs without documents (tailoring not offered): the section has the tabs and no Documents block', () => {
    const html = render({ includeTailor: false })
    expect(count(html, '>AI Tools<')).toBe(1)
    expect(html).not.toContain('data-testid="ai-tools-documents"')
    expect(html).toContain('Analysis')
  })

  it('a kept ad without scores keeps its AI tabs and gets no documents', () => {
    const html = render({}, { jobId: 'k1', title: 'Kept', company: 'C', keptByUser: true, status: 'new' })
    expect(count(html, '>AI Tools<')).toBe(1)
    expect(html).not.toContain('data-testid="ai-tools-documents"')
  })

  it('the document actions are not drawn a second time outside the section', () => {
    const html = render()
    expect(count(html, 'data-testid="tailor-checks-passed"')).toBe(1)
  })
})
