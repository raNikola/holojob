import { cleanKeywordBank, extractMeaningfulPhrases } from './keywordCleaner.js'

function dedupe(arr) {
  return [...new Set(arr.filter(Boolean).map((s) => String(s).trim()))]
}

const LIMITS = {
  highPriority: 20,
  mediumPriority: 25,
  supportingKeywords: 30,
}

export function generateAtsKeywords(ctx, roleStrategy, skillsMap, historySkills = []) {
  // Proven by two or more history entries: high priority. Stated once, or only listed in a CV: medium / supporting.
  const evidenced = historySkills.filter((h) => h.entries >= 2).map((h) => h.term)
  const stated = historySkills.filter((h) => h.entries === 1).map((h) => h.term)
  const listedOnly = historySkills.filter((h) => h.entries === 0).map((h) => h.term)

  const cleanerOptions = {
    workExperience: ctx.parsedData.workExperience,
  }

  const highPriority = cleanKeywordBank(
    dedupe([
      ...ctx.targetRoles,
      ctx.currentRole,
      ...skillsMap.technicalSkills.slice(0, 15),
      ...evidenced,
    ]),
    cleanerOptions,
  ).slice(0, LIMITS.highPriority)

  const mediumPriority = cleanKeywordBank(
    dedupe([
      ...roleStrategy.secondaryTargetRoles,
      ...ctx.parsedData.projects,
      ...ctx.parsedData.certifications,
      ...extractMeaningfulPhrases(ctx.parsedData.workExperience),
      ...stated,
    ]),
    cleanerOptions,
  ).slice(0, LIMITS.mediumPriority)

  const supportingKeywords = cleanKeywordBank(
    dedupe([
      ...ctx.parsedData.education,
      ...ctx.questionnaire.preferredIndustries,
      ...skillsMap.productBusiness,
      ...skillsMap.softSkills,
      ...listedOnly,
    ]),
    cleanerOptions,
  ).slice(0, LIMITS.supportingKeywords)

  const resumeKeywords = dedupe([
    ...highPriority,
    ...mediumPriority.slice(0, 10),
    ...supportingKeywords.slice(0, 5),
  ]).slice(0, 40)

  return {
    resumeKeywords,
    atsKeywordBank: {
      highPriority,
      mediumPriority,
      supportingKeywords,
    },
  }
}
