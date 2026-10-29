import { useEffect, useSyncExternalStore } from 'react'
import { getApplicationsState, refreshApplications, subscribe } from '../modules/applications/applicationsClient.js'

/** The application store cache. Loads it once when the first view asks. */
export function useApplications() {
  const state = useSyncExternalStore(subscribe, getApplicationsState, getApplicationsState)
  useEffect(() => {
    if (state.status === 'idle') refreshApplications()
  }, [state.status])
  return state
}
