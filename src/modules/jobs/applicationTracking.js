export const INTERVIEW_STAGES = [
  'Applied',
  'HR Screen',
  'Technical Round 1',
  'Technical Round 2',
  'Assignment',
  'Hiring Manager',
  'Final Round',
  'Offer',
  'Rejected',
  'Withdrawn',
]

export const TERMINAL_STAGES = new Set(['Offer', 'Rejected', 'Withdrawn', 'Ghosted', 'Position closed', 'Offer declined'])

export function getDefaultApplicationTracking() {
  return {
    applied: false,
    appliedDate: '',
    applicationUrl: '',
    recruiterName: '',
    recruiterEmail: '',
    recruiterLinkedIn: '',
    notes: '',
    followUpDate: '',
    interviewStage: '',
    lastUpdated: '',
  }
}

export function normalizeApplicationTracking(job) {
  return {
    ...getDefaultApplicationTracking(),
    ...(job.applicationTracking || {}),
  }
}
