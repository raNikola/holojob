import { useEffect, useState } from 'react'
import { fetchListCounts } from './jobListClient.js'

/**
 * The numbers of the whole list from the server (`counts.stats`: totals, statuses, tiers, the tracker's cards), or null until they come, when the server list is off,
 * or when the server cannot say: the caller then uses what the browser can work out from its own rows. Reads only.
 */
export function useServerStats({ enabled, stored }) {
  const [stats, setStats] = useState(null)
  useEffect(() => {
    if (!enabled) return undefined
    let alive = true
    fetchListCounts({ stored }).then((answer) => { if (alive) setStats(answer.ok ? answer.counts.stats : null) })
    return () => { alive = false }
  }, [enabled, stored])
  return enabled ? stats : null
}
