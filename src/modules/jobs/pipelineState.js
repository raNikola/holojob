export const PIPELINE_STATE_KEY = 'job-dashboard-pipeline-state'

export function getDefaultPipelineState() {
  return {
    profileExists: false,
    intelligenceExists: false,
    jobsDiscovered: 0,
    jobsScored: 0,
    resumesGenerated: 0,
    lastDiscoveryRun: null,
    lastScoringRun: null,
    lastTailoringRun: null,
    runningStep: null,
  }
}

export function loadPipelineState() {
  try {
    const raw = localStorage.getItem(PIPELINE_STATE_KEY)
    if (!raw) return getDefaultPipelineState()
    return { ...getDefaultPipelineState(), ...JSON.parse(raw) }
  } catch {
    return getDefaultPipelineState()
  }
}

export function savePipelineState(state) {
  localStorage.setItem(PIPELINE_STATE_KEY, JSON.stringify(state))
  return state
}

export function updatePipelineState(patch) {
  const next = { ...loadPipelineState(), ...patch }
  return savePipelineState(next)
}

export function derivePipelineStateFromHealth(health, jobs = []) {
  const scoredCount = jobs.filter((j) => typeof j.matchScore === 'number').length
  const resumeCount = jobs.filter((j) => j.tailoredAssets?.resumeMd).length
  return {
    profileExists: Boolean(health?.profile?.exists),
    intelligenceExists: Boolean(health?.intelligence?.exists),
    jobsDiscovered: health?.discovery?.jobCount ?? jobs.length,
    jobsScored: health?.scoring?.jobCount ?? scoredCount,
    resumesGenerated: health?.tailoring?.tailoredCount ?? resumeCount,
    lastDiscoveryRun: health?.discovery?.generatedAt ?? null,
    lastScoringRun: health?.scoring?.generatedAt ?? null,
    lastTailoringRun: null,
  }
}

// Where the server reports each count. A reported count (0 included) is never taken from the job list.
const SERVER_COUNTS = {
  jobsDiscovered: (health) => health?.discovery?.jobCount,
  jobsScored: (health) => health?.scoring?.jobCount,
  resumesGenerated: (health) => health?.tailoring?.tailoredCount,
}

/**
 * Bring the counts the server does not report in line with the current jobs. Writes, and returns the new state, only
 * when one differs; otherwise returns null, so a job edit that changes no count writes nothing and causes no render.
 * A count the server reports is left alone: the caller's `health` may be older than what auto-refresh stored. So are
 * the run times and runningStep, which belong to whoever set them.
 */
export function syncPipelineCounts(health, jobs) {
  const derived = derivePipelineStateFromHealth(health, jobs)
  const stored = loadPipelineState()
  const changed = Object.keys(SERVER_COUNTS)
    .filter((field) => SERVER_COUNTS[field](health) == null && stored[field] !== derived[field])
  if (!changed.length) return null
  return updatePipelineState(Object.fromEntries(changed.map((field) => [field, derived[field]])))
}
