import { useCallback, useEffect, useState } from 'react'
import { ProfileProvider, useProfile } from './context/ProfileContext'
import DemoBootstrapGate, { useDemoBootstrapContext } from './components/demo/DemoBootstrapGate'
import AppShell from './components/layout/AppShell'
import OnboardingWizard from './components/onboarding/OnboardingWizard'
import DashboardHome from './components/dashboard/DashboardHome'
import ProfileHome from './components/profile/ProfileHome'
import CandidateIntelligenceScreen from './components/intelligence/CandidateIntelligenceScreen'
import JobDiscoveryScreen from './components/jobs/JobDiscoveryScreen'
import ApplicationHome from './components/applications/ApplicationHome'
import ResumeLibrary from './components/resumes/ResumeLibrary'
import CvLibrary from './components/cvs/CvLibrary'
import SettingsHome from './components/settings/SettingsHome'
import CareerStrategyScreen from './components/ai/CareerStrategyScreen'
import AICommandCenter from './components/ai/AICommandCenter'
import OutreachDashboard from './components/outreach/OutreachDashboard'
import QualityDashboard from './components/quality/QualityDashboard'
import JobDetailsPage from './components/jobs/JobDetailsPage'
import { useJobRoute } from './hooks/useJobRoute'
import { useBackgroundRefresh } from './hooks/useBackgroundRefresh'
import { closeJobPage } from './modules/jobs/jobRoute'
import {
  VIEWS,
  isOnboardingComplete,
  OPEN_SETTINGS_EVENT,
  OPEN_QUESTIONNAIRE_EVENT,
  loadDemoInitialView,
  persistView,
} from './modules/appNavigation'

function AppContent() {
  const { profile, startProfileEdit } = useProfile()
  const { demoMode, demoReady } = useDemoBootstrapContext()
  const [view, setViewState] = useState(() => loadDemoInitialView(profile, demoMode))

  const routedJobId = useJobRoute()
  useBackgroundRefresh()

  const setView = useCallback((next) => {
    setViewState(next)
    persistView(next)
  }, [])

  // Choosing a view from the navigation leaves the job page; the page's own Back returns to the previous view.
  const navigate = useCallback((next) => {
    if (routedJobId) closeJobPage()
    setView(next)
  }, [setView, routedJobId])

  useEffect(() => {
    const open = () => navigate(VIEWS.SETTINGS)
    window.addEventListener(OPEN_SETTINGS_EVENT, open)
    return () => window.removeEventListener(OPEN_SETTINGS_EVENT, open)
  }, [navigate])

  useEffect(() => {
    const open = () => {
      startProfileEdit(4)
      navigate(VIEWS.PROFILE_EDIT)
    }
    window.addEventListener(OPEN_QUESTIONNAIRE_EVENT, open)
    return () => window.removeEventListener(OPEN_QUESTIONNAIRE_EVENT, open)
  }, [navigate, startProfileEdit])

  const handleOnboardingComplete = useCallback(() => {
    setView(demoMode ? VIEWS.JOBS : VIEWS.DASHBOARD)
  }, [setView, demoMode])

  const skipOnboarding = demoMode && demoReady && isOnboardingComplete(profile)

  useEffect(() => {
    if (skipOnboarding) {
      setViewState(VIEWS.JOBS)
      persistView(VIEWS.JOBS)
    }
  }, [skipOnboarding])

  if (view === VIEWS.ONBOARDING && !skipOnboarding) {
    return (
      <OnboardingWizard
        mode="onboarding"
        onComplete={handleOnboardingComplete}
      />
    )
  }

  const activeView = view === VIEWS.ONBOARDING && skipOnboarding ? VIEWS.JOBS : view

  return (
    <AppShell activeView={activeView} onNavigate={navigate}>
      {routedJobId && <JobDetailsPage key={routedJobId} jobId={routedJobId} />}
      {!routedJobId && activeView === VIEWS.DASHBOARD && <DashboardHome onNavigate={setView} />}
      {!routedJobId && activeView === VIEWS.PROFILE && <ProfileHome onNavigate={setView} />}
      {!routedJobId && activeView === VIEWS.PROFILE_EDIT && (
        <OnboardingWizard
          mode="edit"
          onComplete={() => setView(VIEWS.PROFILE)}
        />
      )}
      {!routedJobId && activeView === VIEWS.INTELLIGENCE && (
        <CandidateIntelligenceScreen onNavigate={setView} />
      )}
      {!routedJobId && activeView === VIEWS.JOBS && <JobDiscoveryScreen />}
      {!routedJobId && activeView === VIEWS.APPLICATIONS && <ApplicationHome />}
      {!routedJobId && activeView === VIEWS.RESUMES && <ResumeLibrary onNavigate={setView} />}
      {!routedJobId && activeView === VIEWS.CVS && <CvLibrary />}
      {!routedJobId && activeView === VIEWS.CAREER_STRATEGY && <CareerStrategyScreen />}
      {!routedJobId && activeView === VIEWS.AI_COMMAND && <AICommandCenter />}
      {!routedJobId && activeView === VIEWS.OUTREACH && <OutreachDashboard />}
      {!routedJobId && activeView === VIEWS.QUALITY && <QualityDashboard />}
      {!routedJobId && activeView === VIEWS.SETTINGS && <SettingsHome />}
    </AppShell>
  )
}

export default function App() {
  return (
    <ProfileProvider>
        <div className="min-h-screen bg-[var(--color-surface)]">
          <DemoBootstrapGate>
            <AppContent />
          </DemoBootstrapGate>
        </div>
    </ProfileProvider>
  )
}
