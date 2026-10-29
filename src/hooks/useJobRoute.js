import { useEffect, useState } from 'react'
import { JOB_ROUTE_EVENT, parseJobHash } from '../modules/jobs/jobRoute'

/** The job id in the location hash, kept in step with Back, deep links and `openJobPage`. */
export function useJobRoute() {
  const [jobId, setJobId] = useState(() => parseJobHash(window.location.hash))
  useEffect(() => {
    const sync = () => setJobId(parseJobHash(window.location.hash))
    window.addEventListener('popstate', sync)
    window.addEventListener('hashchange', sync)
    window.addEventListener(JOB_ROUTE_EVENT, sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener('hashchange', sync)
      window.removeEventListener(JOB_ROUTE_EVENT, sync)
    }
  }, [])
  return jobId
}
