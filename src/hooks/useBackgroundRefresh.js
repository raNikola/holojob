import { useEffect } from 'react'
import { getApplicationsState, refreshApplications } from '../modules/applications/applicationsClient'
import { POLL_MS, refreshDecision } from '../modules/applications/refreshPolicy'
import { dirtyDraftLabels } from '../modules/jobs/draftGuard'
import { rereadJobs } from '../modules/jobs/jobsStore'

/**
 * Keeps one tab in step with another: when the tab becomes visible or focused, and every 30 s while visible, the
 * application cache is fetched again and the job list is re-read. A draft that would be replaced blocks it.
 */
export function useBackgroundRefresh() {
  useEffect(() => {
    let last = Date.now()
    const run = (trigger) => {
      const decision = refreshDecision({
        trigger,
        visible: document.visibilityState === 'visible',
        status: getApplicationsState().status,
        dirtyLabels: dirtyDraftLabels(),
        sinceLastMs: Date.now() - last,
      })
      if (decision !== 'refresh') return
      last = Date.now()
      refreshApplications()
      rereadJobs()
    }
    const onVisibility = () => run('visible')
    const onFocus = () => run('focus')
    const timer = setInterval(() => run('poll'), POLL_MS)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onFocus)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onFocus)
    }
  }, [])
}
