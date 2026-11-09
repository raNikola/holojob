import { useEffect, useSyncExternalStore } from 'react'
import { getJobState, refreshJobState, subscribe } from '../modules/jobs/jobStateClient.js'

/** The server's job statuses and Keep flags. Loads once when the first view asks; a load saves nothing to the browser. */
export function useJobState() {
  const state = useSyncExternalStore(subscribe, getJobState, getJobState)
  useEffect(() => {
    if (state.status === 'idle') refreshJobState()
  }, [state.status])
  return state
}
