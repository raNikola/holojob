import { useSyncExternalStore } from 'react'
import { getStorageHealth, subscribeStorageHealth } from '../modules/jobs/storageHealth.js'

export function useStorageHealth() {
  return useSyncExternalStore(subscribeStorageHealth, getStorageHealth, getStorageHealth)
}
