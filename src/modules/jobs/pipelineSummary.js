/** One line for the end of a full pipeline run, from the summary python/run_pipeline.py returns. */
export function describeRun(summary, jobCount) {
  if (!summary) return `Pipeline complete: ${jobCount} jobs scored, resumes generated`
  const parts = [`${summary.discovery?.deduped ?? jobCount} discovered`]
  const providers = Object.entries(summary.discovery?.providerCounts || {}).filter(([, n]) => n > 0)
  if (providers.length) parts[0] += ` (${providers.map(([k, n]) => `${k} ${n}`).join(', ')})`
  if (summary.enrichment?.enrichedShare != null) parts.push(`${Math.round(summary.enrichment.enrichedShare * 100)}% read by the model`)
  const sc = summary.scoring
  if (sc) {
    parts.push(`${sc.jobs} scored`)
    const p = sc.priority || {}
    parts.push(`P1 ${p.P1 || 0} · P2 ${p.P2 || 0}`)
    if (sc.hardCapped) parts.push(`${sc.hardCapped} capped by a hard rule`)
  }
  return `Pipeline complete: ${parts.join(', ')}; resumes generated`
}
