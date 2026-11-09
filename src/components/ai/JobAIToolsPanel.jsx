import { useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw, Sparkles } from 'lucide-react'
import Tabs from '../ui/Tabs'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import OperationConsole from '../ui/OperationConsole'
import { useOperationLog } from '../../hooks/useOperationLog'
import { runAiFeature } from '../../modules/ai/aiClient'
import { REGENERATE_CONFIRM, analysisButtonState, fetchFindingStatus, regenerateDecision } from '../../modules/ai/findingStatus'
import OutreachComposer from '../outreach/OutreachComposer'
import CoverLetterAccept from './CoverLetterAccept'
import { rankContacts } from '../../modules/outreach/contactRanking'
import { isApiAvailable } from '../../utils/apiAvailability'

const TABS = [
  { id: 'analysis', label: 'Analysis' },
  { id: 'interview', label: 'Interview' },
  { id: 'outreach', label: 'Outreach' },
  { id: 'company', label: 'Company' },
  { id: 'cover', label: 'Cover Letter' },
]

const FEATURE_MAP = {
  analysis: 'jobAnalysis',
  interview: 'interviewPrep',
  outreach: 'outreach',
  company: 'companyIntelligence',
  cover: 'coverLetter',
}

/** Tabs whose answer is kept as a finding on the server and can be checked without a call. */
const FINDING_TABS = {
  analysis: { feature: 'jobAnalysis', verb: 'analysed' },
  company: { feature: 'companyIntelligence', verb: 'researched' },
}

function InsightBlock({ data, fields }) {
  if (!data) return null
  return (
    <div className="space-y-3 text-sm">
      {fields.map(({ key, label, list }) => (
        <div key={key}>
          {label && <p className="text-xs font-semibold uppercase text-stone-500">{label}</p>}
          {list && Array.isArray(data[key]) ? (
            <ul className="mt-1 list-inside list-disc text-stone-700 dark:text-stone-300">
              {data[key].map((item) => <li key={String(item)}>{typeof item === 'object' ? JSON.stringify(item) : item}</li>)}
            </ul>
          ) : (
            <p className="mt-1 text-stone-700 dark:text-stone-300">{data[key] || '—'}</p>
          )}
        </div>
      ))}
    </div>
  )
}

/**
 * The one "AI Tools" section of a job. `documents` (the document actions: generate, download, evaluate) sits at the top,
 * above whatever else the section holds. Used with the AI tabs on the details page, and on its own where the tabs are not
 * offered (the side drawer), so the heading is the same everywhere.
 */
export function AiToolsSection({ documents = null, children = null }) {
  return (
    <details className="rounded-xl border border-stone-200 dark:border-stone-800" open data-testid="ai-tools-section">
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-stone-800 dark:text-stone-200">
        <span className="inline-flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-teal-600" />
          AI Tools
        </span>
      </summary>
      <div className="space-y-4 border-t border-stone-200 px-4 py-4 dark:border-stone-800">
        {documents && (
          <section aria-label="Documents" data-testid="ai-tools-documents" className={children ? 'border-b border-stone-200 pb-4 dark:border-stone-800' : undefined}>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-stone-500">Documents</h4>
            {documents}
          </section>
        )}
        {children}
      </div>
    </details>
  )
}

export default function JobAIToolsPanel({ job, onJobUpdated, documents = null }) {
  const [tab, setTab] = useState('analysis')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const log = useOperationLog()
  const inFlight = useRef(false)

  const insights = job.aiInsights || {}

  // Is the answer of this tab still valid on the server? Asked again whenever the job, the tab or a run changes.
  const [findingStatus, setFindingStatus] = useState(null)
  const findingTab = FINDING_TABS[tab]
  useEffect(() => {
    if (!findingTab || loading || !isApiAvailable()) return undefined
    let current = true
    fetchFindingStatus(findingTab.feature, { job }).then((status) => { if (current) setFindingStatus({ ...status, jobId: job.jobId, tab }) })
    return () => { current = false }
  }, [tab, findingTab, job, loading])

  const persist = (featureKey, data, meta) => {
    const patch = {
      [featureKey]: data,
      provider: meta?.provider,
      model: meta?.model,
      generatedAt: meta?.generatedAt,
    }
    onJobUpdated?.({
      ...job,
      aiInsights: { ...(job.aiInsights || {}), ...patch },
    })
  }

  const run = async (tabId, skipCache = false) => {
    if (inFlight.current) return
    inFlight.current = true
    const featureId = FEATURE_MAP[tabId]
    setError(null)
    setLoading(true)
    log.start(`Starting ${featureId}…`)
    try {
      const result = await runAiFeature(featureId, { job, skipCache, onLog: log.append })
      const keyMap = {
        jobAnalysis: 'jobAnalysis',
        interviewPrep: 'interviewPrep',
        outreach: 'outreachDrafts',
        companyIntelligence: 'companyIntelligence',
        coverLetter: 'coverLetter',
      }
      persist(keyMap[featureId], result.data, result.meta)
      log.append('Done.')
    } catch (e) {
      setError(e.message)
      log.append(`Error: ${e.message}`)
    } finally {
      inFlight.current = false
      setLoading(false)
      log.stop()
    }
  }

  const renderContent = () => {
    if (tab === 'analysis') {
      return (
        <InsightBlock
          data={insights.jobAnalysis}
          fields={[
            { key: 'fitSummary', label: 'Fit summary' },
            { key: 'strengths', label: 'Strengths', list: true },
            { key: 'concerns', label: 'Concerns', list: true },
            { key: 'missingSkills', label: 'Missing skills', list: true },
            { key: 'recommendedActions', label: 'Actions', list: true },
            { key: 'riskLevel', label: 'Risk' },
          ]}
        />
      )
    }
    if (tab === 'interview') {
      return (
        <InsightBlock
          data={insights.interviewPrep}
          fields={[
            { key: 'cheatSheet', label: 'Cheat sheet' },
            { key: 'technicalQuestions', label: 'Technical', list: true },
            { key: 'behavioralQuestions', label: 'Behavioral', list: true },
            { key: 'revisionTopics', label: 'Revision topics', list: true },
          ]}
        />
      )
    }
    if (tab === 'outreach') {
      const contacts = job.outreach?.contacts || []
      const ranking = rankContacts(contacts)
      const primary = ranking.recommendedPrimaryContact
      return (
        <div className="space-y-4">
          {primary ? (
            <OutreachComposer job={job} contact={primary} onJobUpdated={onJobUpdated} compact />
          ) : (
            <p className="text-sm text-stone-500">
              Add contacts in Related Contacts below, or generate generic drafts.
            </p>
          )}
          {!primary && insights.outreachDrafts && (
            <div className="space-y-3 text-sm">
              {['connectionRequest', 'inMail', 'followUp', 'thankYou'].map((k) => (
                <div key={k}>
                  <p className="text-xs font-semibold uppercase text-stone-500">{k}</p>
                  <p className="mt-1 whitespace-pre-wrap text-stone-700 dark:text-stone-300">{insights.outreachDrafts[k]}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }
    if (tab === 'company') {
      return (
        <InsightBlock
          data={insights.companyIntelligence}
          fields={[
            { key: 'companySummary', label: 'Summary' },
            { key: 'cultureInsights', label: 'Culture', list: true },
            { key: 'likelyInterviewFocus', label: 'Interview focus', list: true },
            { key: 'risks', label: 'Risks', list: true },
          ]}
        />
      )
    }
    if (tab === 'cover') {
      const d = insights.coverLetter
      if (!d) return null
      return (
        <div className="space-y-3 text-sm">
          {['short', 'standard', 'aggressive'].map((k) => (
            <div key={k}>
              <p className="text-xs font-semibold uppercase text-stone-500">{k}</p>
              <p className="mt-1 whitespace-pre-wrap text-stone-700 dark:text-stone-300">{d[k]}</p>
            </div>
          ))}
          {insights.generatedAt && isApiAvailable() && <CoverLetterAccept jobId={job.jobId} />}
        </div>
      )
    }
    return null
  }

  const labels = {
    analysis: 'Analyze Job with AI',
    interview: 'Generate Interview Prep',
    outreach: 'Draft Outreach Messages',
    company: 'Research Company',
    cover: 'Generate Cover Letters',
  }

  const currentStatus = findingTab && findingStatus?.jobId === job.jobId && findingStatus.tab === tab ? findingStatus : null
  const regenerate = regenerateDecision({ status: currentStatus, loading })
  const onRegenerate = () => {
    const { action } = regenerateDecision({ status: currentStatus, loading, inFlight: inFlight.current })
    if (action === 'ignore') return
    if (action === 'confirm' && !window.confirm(REGENERATE_CONFIRM)) return
    run(tab, true)
  }

  const primary = findingTab
    ? analysisButtonState({ status: currentStatus, hasAnalysis: Boolean(insights[findingTab.feature]), loading, verb: findingTab.verb })
    : { disabled: loading, title: '' }

  return (
    <AiToolsSection documents={documents}>
      <div className="space-y-4">
        <Tabs tabs={TABS} active={tab} onChange={setTab} />
        {error && <Alert variant="error" title="AI error">{error}</Alert>}
        <div className="flex gap-2">
          <Button onClick={() => run(tab)} disabled={primary.disabled} title={primary.title || undefined}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {labels[tab]}
          </Button>
          <Button variant="ghost" onClick={onRegenerate} disabled={regenerate.disabled} title="Ask the AI again, even if nothing changed (this counts against the budget)" aria-label="Ask the AI again">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
        <OperationConsole
          lines={log.lines}
          active={log.active}
          title={loading ? 'AI working…' : 'Activity log'}
        />
        <p className="text-xs text-stone-500">AI suggestions only — verify against your profile. No auto-send.</p>
        {renderContent()}
      </div>
    </AiToolsSection>
  )
}
