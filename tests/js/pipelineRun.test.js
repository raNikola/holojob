import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import { describeRun } from '../../src/modules/jobs/pipelineSummary.js'
import { parseStoppedStep } from '../../scripts/run-pipeline.js'

describe('full pipeline', () => {
  it('summarises a run from the orchestrator summary', () => {
    const line = describeRun({
      discovery: { deduped: 393, providerCounts: { jobspy: 300, greenhouse: 93, lever: 0 } },
      enrichment: { enrichedShare: 0.91 },
      scoring: { jobs: 393, priority: { P1: 143, P2: 83 }, hardCapped: 100 },
    }, 393)
    expect(line).toContain('393 discovered (jobspy 300, greenhouse 93)')
    expect(line).toContain('91% read by the model')
    expect(line).toContain('P1 143 · P2 83')
    expect(line).not.toContain('lever')
  })

  it('names the step that stopped the run', () => {
    expect(parseStoppedStep('noise\nPIPELINE STOPPED at enrichment: only 50% of jobs have facts\nNot run: scoring.'))
      .toEqual({ failedStep: 'enrichment', reason: 'only 50% of jobs have facts' })
    expect(parseStoppedStep('some other error')).toEqual({ failedStep: null, reason: null })
  })

  it('the button runs one server-side pipeline, not discovery and scoring separately, and never judges', () => {
    const ui = fs.readFileSync('src/components/jobs/PipelineOrchestrator.jsx', 'utf8')
    const full = ui.slice(ui.indexOf('const handleFullPipeline'), ui.indexOf('}, [syncInputs, providers, country, profile, importPayload, runTailorStep])'))
    expect(full).toContain('runFullPipeline(')
    expect(full).not.toMatch(/runDiscovery\(|runScoring\(|runJudgedScoring/)
    const route = fs.readFileSync('scripts/run-pipeline.js', 'utf8')
    expect(route).not.toContain("'--judge'")
  })
})
