import { useEffect } from 'react'
import { setDraftDirty } from '../modules/jobs/draftGuard'

/** Reports whether a form holds unsaved input; cleared when the form unmounts. */
export function useDraftDirty(key, label, isDirty) {
  useEffect(() => {
    setDraftDirty(key, label, isDirty)
    return () => setDraftDirty(key, label, false)
  }, [key, label, isDirty])
}
