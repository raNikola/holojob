import { createContext, useContext, useCallback, useEffect, useState } from 'react'
import { loadProfile, saveProfile, restoreProfile as restoreStorage, clearProfile as clearStorage, getDefaultProfile } from '../utils/storage'
import { applyToDefaultCv } from '../utils/cvAnalysis'
import { addCv, patchCvAnalysis, removeCv, renameCv, setCvAnalysis, setDefaultCv } from '../utils/cvLibrary'
import { unansweredQuestionIds } from '../modules/profile/questionnaireStatus'

const ProfileContext = createContext(null)

export function ProfileProvider({ children }) {
  const [profile, setProfile] = useState(() => loadProfile())
  const [currentStep, setCurrentStep] = useState(() => profile.meta?.lastStep ?? 0)

  useEffect(() => {
    const saved = loadProfile()
    setProfile(saved)
    setCurrentStep(saved.meta?.lastStep ?? 0)
  }, [])

  const updateProfile = useCallback((updater) => {
    setProfile((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : { ...prev, ...updater }
      return saveProfile(next)
    })
  }, [])

  const setStep = useCallback((step) => {
    setCurrentStep(step)
    setProfile((prev) => saveProfile({ ...prev, meta: { ...prev.meta, lastStep: step } }))
  }, [])

  // CV library actions (profile.cvLibrary). All are pure profile updates; the
  // files themselves are stored and deleted through modules/cvs/cvApi.
  const cvActions = {
    addCv: (entry, options) => setProfile((prev) => saveProfile(addCv(prev, entry, options))),
    setDefaultCv: (id) => setProfile((prev) => saveProfile(setDefaultCv(prev, id))),
    renameCv: (id, label) => setProfile((prev) => saveProfile(renameCv(prev, id, label))),
    removeCv: (id) => setProfile((prev) => saveProfile(removeCv(prev, id))),
    setCvAnalysis: (id, analysis) => setProfile((prev) => saveProfile(setCvAnalysis(prev, id, analysis))),
    patchCvAnalysis: (id, patch) => setProfile((prev) => saveProfile(patchCvAnalysis(prev, id, patch))),
    // Only the default CV is applied: its data is what the rest of the app reads.
    // Returns { profile, count } (the new profile, for regenerating intelligence) or null.
    applyCvAnalysis: (id, selected) => {
      const result = applyToDefaultCv(profile, id, selected)
      if (result && result.count > 0) setProfile(saveProfile(result.profile))
      return result
    },
  }

  const markFieldEdited = useCallback((fieldKey) => {
    setProfile((prev) => saveProfile({
      ...prev,
      _editedFields: { ...prev._editedFields, [fieldKey]: true },
    }))
  }, [])

  const resetProfile = useCallback(() => {
    clearStorage()
    const fresh = getDefaultProfile()
    setProfile(fresh)
    setCurrentStep(0)
  }, [])

  const markOnboardingComplete = useCallback(() => {
    setProfile((prev) => saveProfile({
      ...prev,
      meta: {
        ...prev.meta,
        onboardingComplete: true,
        completedAt: new Date().toISOString(),
        // Finished with questions still unknown; drives the "Complete your profile" card.
        onboardingFinishedEarly: unansweredQuestionIds(prev).length > 0,
      },
    }))
  }, [])

  // "Not now" on the Complete your profile card.
  const dismissCompleteProfile = useCallback(() => {
    setProfile((prev) => saveProfile({
      ...prev,
      meta: { ...prev.meta, completeProfileDismissedAt: new Date().toISOString() },
    }))
  }, [])

  const startProfileEdit = useCallback((step = 1) => {
    setCurrentStep(step)
    setProfile((prev) => saveProfile({ ...prev, meta: { ...prev.meta, lastStep: step } }))
  }, [])

  // Cancel in Edit Profile: put back the profile as it was when the edit began,
  // in state and in localStorage.
  const restoreProfile = useCallback((snapshot) => {
    setProfile(restoreStorage(snapshot))
    setCurrentStep(snapshot.meta?.lastStep ?? 0)
  }, [])

  return (
    <ProfileContext.Provider value={{
      profile,
      currentStep,
      updateProfile,
      setStep,
      markFieldEdited,
      resetProfile,
      markOnboardingComplete,
      dismissCompleteProfile,
      startProfileEdit,
      restoreProfile,
      cvActions,
    }}>
      {children}
    </ProfileContext.Provider>
  )
}

export function useProfile() {
  const ctx = useContext(ProfileContext)
  if (!ctx) throw new Error('useProfile must be used within ProfileProvider')
  return ctx
}
