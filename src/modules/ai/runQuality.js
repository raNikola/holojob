/**
 * Was the last scored run reduced because the AI budget gate refused? Read from the quality
 * object python/run_pipeline.py writes into scored_jobs.json meta (so cron runs count too).
 * A run the owner chose to skip enrichment for (--skip-enrich) is reduced but not refused.
 */
const REFUSED_PREFIX = 'AI enrichment refused'

export function gateRefusalReason(meta) {
  const quality = meta?.quality
  if (!quality?.reduced || typeof quality.reason !== 'string') return null
  return quality.reason.startsWith(REFUSED_PREFIX) ? quality.reason : null
}
