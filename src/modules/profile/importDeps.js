// The real effects of an import apply (see importApply.js): browser storage, the profile mirror and the backup route.

import { backupProfileForImport, saveProfileToDataDir } from '../jobs/profileSync.js'
import { loadProfile, saveProfile } from '../../utils/storage.js'
import { uploadCvFile, deleteCvFile } from '../cvs/cvApi.js'

export const SYNC_PENDING_KEY = 'job-dashboard-profile-sync-pending'
export const INTELLIGENCE_STALE_KEY = 'job-dashboard-intelligence-stale'

const read = (key) => { try { return localStorage.getItem(key) } catch { return null } }
const write = (key, value) => { try { localStorage.setItem(key, value) } catch { /* a flag that cannot be stored is not shown */ } }
const drop = (key) => { try { localStorage.removeItem(key) } catch { /* nothing to remove */ } }

export const isSyncPending = () => read(SYNC_PENDING_KEY) === '1'
export const isIntelligenceStale = () => read(INTELLIGENCE_STALE_KEY) === '1'
export const clearIntelligenceStale = () => drop(INTELLIGENCE_STALE_KEY)

// The pre-import copy for Undo is held in memory only: browser storage may hold UI state and nothing more
// (src/modules/browserStorage/allowlist.js), and a second copy of the profile is not that. Undo therefore lasts until the page is
// reloaded; the durable copy is the backup the server made before the write (data/backups/profile-import-*).
let memorySnapshot = null
export const snapshotStore = {
  saveBefore(profile) {
    memorySnapshot = { before: JSON.parse(JSON.stringify(profile)), after: null }
  },
  saveAfter(profile) {
    if (memorySnapshot) memorySnapshot = { ...memorySnapshot, after: JSON.parse(JSON.stringify(profile)) }
  },
  load() {
    return memorySnapshot?.before && memorySnapshot?.after ? memorySnapshot : null
  },
  clear() { memorySnapshot = null },
}

/**
 * @param {{ commitToScreen?: (profile: object) => void }} [screen] tells the React state what was stored
 */
export function realImportDeps({ commitToScreen } = {}) {
  return {
    backup: backupProfileForImport,
    snapshot: snapshotStore,
    upload: uploadCvFile,
    discardUpload: (id) => deleteCvFile(id),
    // saveProfile stamps updatedAt and throws when the browser store is full; nothing is changed then.
    commit: (profile) => {
      const saved = saveProfile(profile)
      commitToScreen?.(saved)
      return saved
    },
    syncMirror: async (profile) => (await saveProfileToDataDir(profile)).ok === true,
    setSyncPending: (pending) => (pending ? write(SYNC_PENDING_KEY, '1') : drop(SYNC_PENDING_KEY)),
    markIntelligenceStale: () => write(INTELLIGENCE_STALE_KEY, '1'),
  }
}

export const currentProfile = () => loadProfile()
