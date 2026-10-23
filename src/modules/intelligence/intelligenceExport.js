import { saveIntelligenceToDataDir } from '../jobs/intelligenceSync'
import { generateCandidateIntelligence } from './candidateIntelligenceEngine'

/** @typedef {import('../../types/career-os.d.ts').CandidateIntelligence} CandidateIntelligence */

export const INTELLIGENCE_STORAGE_KEY = 'job-dashboard-candidate-intelligence'

/** @param {CandidateIntelligence} intelligence */
export function saveIntelligence(intelligence) {
  localStorage.setItem(INTELLIGENCE_STORAGE_KEY, JSON.stringify(intelligence))
  return intelligence
}

/** @returns {CandidateIntelligence|null} */
export function loadIntelligence() {
  try {
    const raw = localStorage.getItem(INTELLIGENCE_STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * Generate intelligence from the profile, keeping the scoring weights saved on
 * the intelligence already in the browser. Every Regenerate action goes through
 * here, so a regeneration never discards weights set in Settings.
 *
 * @param {import('../../types/career-os.d.ts').Profile} profile
 * @param {object} [options] passed to generateCandidateIntelligence
 */
export function regenerateIntelligence(profile, options = {}) {
  return generateCandidateIntelligence(profile, { ...options, previousIntelligence: loadIntelligence() })
}

export function clearIntelligence() {
  localStorage.removeItem(INTELLIGENCE_STORAGE_KEY)
}

export function buildIntelligenceExport(intelligence) {
  return JSON.parse(JSON.stringify(intelligence))
}

export async function downloadCandidateIntelligence(intelligence) {
  const blob = new Blob([JSON.stringify(buildIntelligenceExport(intelligence), null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'candidate-intelligence.json'
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
  return saveIntelligenceToDataDir(intelligence)
}
