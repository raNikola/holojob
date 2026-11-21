import { tierCounts } from './fitTier.js'
import { isClosedAd } from './jobHistory.js'

/** One line for the end of a full pipeline run, from the summary python/run_pipeline.py returns. */
export function describeRun(summary, jobCount, scoredJobs = null) {
  if (!summary) return `Pipeline complete: ${jobCount} jobs scored, resumes generated`
  const parts = [`${summary.discovery?.deduped ?? jobCount} discovered`]
  const providers = Object.entries(summary.discovery?.providerCounts || {}).filter(([, n]) => n > 0)
  if (providers.length) parts[0] += ` (${providers.map(([k, n]) => `${k} ${n}`).join(', ')})`
  if (summary.enrichment?.enrichedShare != null) parts.push(`${Math.round(summary.enrichment.enrichedShare * 100)}% read by the model`)
  const sc = summary.scoring
  if (sc) {
    parts.push(`${sc.jobs} scored`)
    // Tier counts (owner decision 2026-11-21): P1 / P2 are score thresholds, not a proven better fit. Without the scored rows the line says nothing about them.
    if (Array.isArray(scoredJobs)) {
      const tiers = tierCounts(scoredJobs, (j) => !isClosedAd(j))
      parts.push(`Strong fit ${tiers.strong} · Possible fit ${tiers.possible}`)
    }
    if (sc.hardCapped) parts.push(`${sc.hardCapped} capped by a hard rule`)
  }
  // The AI budget gate refused enrichment (or it was skipped): the scores stand, read without the ad facts.
  if (summary.quality?.reduced) parts.push(`REDUCED QUALITY (${summary.quality.reason})`)
  return `Pipeline complete: ${parts.join(', ')}; resumes generated`
}
