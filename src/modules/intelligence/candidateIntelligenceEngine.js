import { normalizeProfile } from './profileNormalizer.js'
import { classifySkills } from './skillsClassifier.js'
import { generateRoleStrategy } from './roleStrategyGenerator.js'
import { generateAtsKeywords } from './atsKeywordGenerator.js'
import { generateSearchStrategy } from './searchStrategyGenerator.js'
import {
  buildCandidateSummary,
  buildExperienceMap,
  buildJobFitPreferences,
} from './candidateNarrativeBuilder.js'
import { validateIntelligenceMapping } from './intelligenceValidators.js'
import { runIntelligenceQualityChecks } from './intelligenceQualityChecks.js'
import { buildCandidateStrengths } from './strengthsBuilder.js'
import { formatLanguages } from '../../utils/languages.js'
import { normalizeRoleFamily } from '../../utils/roleFamily.js'
import defaultWeights from '../../data/scoringWeights.json'

// The one set of default weights, shared with the settings panel and the Python
// scorer (python/job_scoring/scorer.py reads the same file).
export const DEFAULT_SCORING_WEIGHTS = defaultWeights

/**
 * The weights a generated intelligence carries: the ones already saved on the
 * previous intelligence (the Settings panel stores them there), with any
 * missing or malformed key filled from the defaults. With nothing saved yet,
 * the defaults. Saved values are kept as they are, not rescaled.
 */
export function resolveScoringWeights(saved) {
  const resolved = {}
  for (const [key, fallback] of Object.entries(DEFAULT_SCORING_WEIGHTS)) {
    const value = saved?.[key]
    resolved[key] = typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : fallback
  }
  return resolved
}

/** @typedef {import('../../types/holojob.d.ts').Profile} Profile */
/** @typedef {import('../../types/holojob.d.ts').CandidateIntelligence} CandidateIntelligence */

/**
 * @param {Profile} rawProfile
 * @param {object} [options]
 * @returns {CandidateIntelligence}
 */
export function generateCandidateIntelligence(rawProfile, options = {}) {
  const ctx = normalizeProfile(rawProfile)
  const skillsMap = classifySkills(ctx)
  const roleStrategy = generateRoleStrategy(ctx)
  const { resumeKeywords, atsKeywordBank } = generateAtsKeywords(ctx, roleStrategy, skillsMap)
  const searchStrategy = generateSearchStrategy(ctx, roleStrategy, skillsMap)
  const candidateSummary = buildCandidateSummary(ctx, skillsMap)
  const experienceMap = buildExperienceMap(ctx)
  const jobFitPreferences = buildJobFitPreferences(ctx)

  const candidateStrengths = buildCandidateStrengths(ctx, skillsMap)

  const candidateWeaknesses = ctx.questionnaire.candidateWeaknesses.slice(0, 6)

  const intelligence = {
    candidateSummary,
    roleStrategy,
    skillsMap,
    experienceMap,
    jobFitPreferences,
    candidateStrengths,
    candidateWeaknesses,
    resumeKeywords,
    atsKeywordBank,
    searchStrategy,
    // Derived from basicProfile.languages ("Serbian (native)"); the fit judge's
    // digest reads this list, so it is never typed in by hand here.
    languages: formatLanguages(ctx.basicProfile?.languages),
    // The family the candidate chose in the profile (src/data/roleFamilies.json);
    // null when none is chosen, and scoring then assumes none.
    roleFamily: normalizeRoleFamily(ctx.basicProfile?.roleFamily) || null,
    scoringWeights: resolveScoringWeights(options.previousIntelligence?.scoringWeights),
    meta: {
      generatedAt: new Date().toISOString(),
      sourceProfileVersion: ctx.profile.meta?.profileVersion || '1.0',
      intelligenceVersion: '1.0',
    },
  }

  if (typeof options.enrichFn === 'function') {
    return options.enrichFn(intelligence, ctx)
  }

  if (options.validateMapping !== false) {
    validateIntelligenceMapping(intelligence)
  }

  if (options.qualityChecks !== false) {
    runIntelligenceQualityChecks(intelligence)
  }

  return intelligence
}
