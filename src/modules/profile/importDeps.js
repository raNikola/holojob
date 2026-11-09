// The real effects of an import apply (see importApply.js): browser storage, the profile mirror and the backup route.

import { backupProfileForImport, saveProfileToDataDir } from '../jobs/profileSync.js'
import { loadProfile, saveProfile } from '../../utils/storage.js'
import { uploadCvFile, deleteCvFile } from '../cvs/cvApi.js'

export const PRE_IMPORT_KEY = 'job-dashboard-profile-pre-import'
export const SYNC_PENDING_KEY = 'job-dashboard-profile-sync-pending'
export const INTELLIGENCE_STALE_KEY = 'job-dashboard-intelligence-stale'

const read = (key) => { try { return localStorage.getItem(key) } catch { return null } }
const write = (key, value) => { try { localStorage.setItem(key, value) } catch { /* a flag that cannot be stored is not shown */ } }
const drop = (key) => { try { localStorage.removeItem(key) } catch { /* nothing to remove */ } }

export const isSyncPending = () => read(SYNC_PENDING_KEY) === '1'
export const isIntelligenceStale = () => read(INTELLIGENCE_STALE_KEY) === '1'
export const clearIntelligenceStale = () => drop(INTELLIGENCE_STALE_KEY)

/** One pre-import copy and the profile the import produced (for Undo). Both stay in this browser, like the profile itself. */
export const snapshotStore = {
  saveBefore(profile) {
    localStorage.setItem(PRE_IMPORT_KEY, JSON.stringify({ before: profile, after: null }))
  },
  saveAfter(profile) {
    const saved = JSON.parse(localStorage.getItem(PRE_IMPORT_KEY))
    localStorage.setItem(PRE_IMPORT_KEY, JSON.stringify({ ...saved, after: profile }))
  },
  load() {
    try {
      const saved = JSON.parse(read(PRE_IMPORT_KEY))
      return saved?.before && saved?.after ? saved : null
    } catch { return null }
  },
  clear() { drop(PRE_IMPORT_KEY) },
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
