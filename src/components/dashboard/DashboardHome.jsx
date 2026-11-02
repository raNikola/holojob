import { useEffect, useMemo, useState } from 'react'
import { Briefcase, ClipboardList, Pencil, Zap } from 'lucide-react'
import Button from '../ui/Button'
import StatCard from '../ui/StatCard'
import { useProfile } from '../../context/ProfileContext'
import { validateProfileForIntelligence } from '../../modules/intelligence/intelligenceValidators'
import { loadIntelligence } from '../../modules/intelligence/intelligenceExport'
import { loadJobs } from '../../modules/jobs/jobStorage'
import { computeJobStats, countTailoredResumes } from '../../modules/jobs/jobStats'
import { computeOutreachMetrics } from '../../modules/outreach/outreachMetrics'
import { trackerStats } from '../../modules/applications/trackingView'
import { useApplications } from '../../hooks/useApplications'
import { probePipelineApi } from '../../modules/jobs/pipelineRunner'
import { isApiAvailable } from '../../utils/apiAvailability'
import { JOBS_TAB_STORAGE_KEY, VIEWS } from '../../modules/appNavigation'

export default function DashboardHome({ onNavigate }) {
  const { profile } = useProfile()
  const [apiStatus, setApiStatus] = useState(null)

  const validation = useMemo(() => validateProfileForIntelligence(profile), [profile])
  const intelligence = useMemo(() => loadIntelligence(), [])
  const jobState = useMemo(() => loadJobs(), [])
  const applications = useApplications()
  const storeReady = applications.status === 'ready'
  const stats = useMemo(
    // The tracker cards count applications from the store, whether or not their ad still has a row.
    () => ({ ...computeJobStats(jobState.jobs), ...trackerStats(storeReady ? applications.store : null, applications.settings) }),
    [jobState.jobs, storeReady, applications.store, applications.settings],
  )
  const trackerLoading = applications.status === 'idle' || applications.status === 'loading'
  const outreachMetrics = useMemo(() => computeOutreachMetrics(jobState.jobs), [jobState.jobs])

  const resumeCount = useMemo(
    () => countTailoredResumes(jobState.jobs),
    [jobState.jobs],
  )

  useEffect(() => {
    probePipelineApi().then((probe) => setApiStatus(probe.available ? 'connected' : 'offline'))
  }, [])

  const goToPipeline = () => {
    try {
      sessionStorage.setItem(JOBS_TAB_STORAGE_KEY, 'pipeline')
    } catch {
      /* ignore */
    }
    onNavigate(VIEWS.JOBS)
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Welcome back{profile.basicProfile?.fullName ? `, ${profile.basicProfile.fullName.split(' ')[0]}` : ''}.
          Your Holojob at a glance.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Profile readiness"
          value={validation.valid ? 'Ready' : 'Incomplete'}
          subtext={validation.valid ? 'All required fields complete' : `${validation.errors?.length || 0} items needed`}
        />
        <StatCard
          label="Intelligence"
          value={intelligence ? 'Generated' : 'Missing'}
          subtext={intelligence?.meta?.generatedAt
            ? new Date(intelligence.meta.generatedAt).toLocaleDateString()
            : 'Generate from profile'}
        />
        <StatCard label="Jobs discovered" value={stats.total} />
        <StatCard label="Jobs scored" value={stats.scored} subtext={stats.avgScore != null ? `Avg score ${stats.avgScore}` : undefined} />
        <StatCard label="Resumes generated" value={resumeCount} />
        <StatCard label="Applications" value={trackerLoading ? '…' : stats.crmApplied} />
        <StatCard
          label="Follow-ups due"
          value={trackerLoading ? '…' : stats.crmFollowUpsDue + outreachMetrics.followUpsDue}
          subtext={outreachMetrics.followUpsDue > 0 ? `${outreachMetrics.followUpsDue} outreach` : undefined}
        />
        {isApiAvailable() && (
          <StatCard
            label="Pipeline API"
            value={apiStatus === 'connected' ? 'Online' : apiStatus === 'offline' ? 'Offline' : '…'}
          />
        )}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <Button onClick={goToPipeline}>
          <Zap className="h-4 w-4" />
          Run Full Pipeline
        </Button>
        <Button variant="secondary" onClick={() => onNavigate(VIEWS.JOBS)}>
          <Briefcase className="h-4 w-4" />
          View Jobs
        </Button>
        <Button variant="secondary" onClick={() => onNavigate(VIEWS.APPLICATIONS)}>
          <ClipboardList className="h-4 w-4" />
          View Applications
        </Button>
        <Button variant="secondary" onClick={() => onNavigate(VIEWS.PROFILE)}>
          <Pencil className="h-4 w-4" />
          Edit Profile
        </Button>
      </div>
    </div>
  )
}
