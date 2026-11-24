import { useEffect, useRef } from 'react'
import { fetchPipelineHealth, loadLatestScoredJobs } from './pipelineRunner'
import { importJobsFromFile } from './jobStorage'
import { derivePipelineStateFromHealth, updatePipelineState } from './pipelineState'
import { isApiAvailable } from '../../utils/apiAvailability.js'

// `refreshRows`: with the server's list the browser holds only the ads the owner worked on, so a new scoring brings those rows up to date (and the list is read
// again) instead of loading the whole scored file. Without it the file is imported, as ever.
export function usePipelineAutoRefresh({ enabled, state, onImport, refreshRows = null }) {
  const lastScoredAt = useRef(null)

  useEffect(() => {
    if (!enabled || !isApiAvailable()) return undefined

    const poll = async () => {
      try {
        const health = await fetchPipelineHealth()
        const scoredAt = health?.scoring?.generatedAt
        if (scoredAt && scoredAt !== lastScoredAt.current) {
          lastScoredAt.current = scoredAt
          if (refreshRows) {
            await refreshRows(health)
            return
          }
          const payload = await loadLatestScoredJobs()
          const next = importJobsFromFile(payload, state)
          onImport({ ...next, meta: payload.meta || next.meta })
          updatePipelineState(derivePipelineStateFromHealth(health, next.jobs))
        }
      } catch {
        // ignore polling errors
      }
    }

    poll()
    const id = setInterval(poll, 30000)
    return () => clearInterval(id)
  }, [enabled, state, onImport, refreshRows])
}
