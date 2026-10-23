function dedupe(arr) {
  return [...new Set(arr.filter(Boolean))]
}

const REMOTE_MAP = {
  remote: ['remote', 'work from home', 'wfh'],
  hybrid: ['hybrid', 'flexible'],
  office: ['on-site', 'onsite', 'in-office'],
  flexible: ['remote', 'hybrid', 'flexible'],
}

// Regions outside the candidate's own country are searched only when they said
// they would move; each name is search text, not a market assumption. Roles
// there that need a visa the candidate lacks are flagged by scoring, not hidden.
const RELOCATION_REGIONS = ['Europe', 'United States']

export function generateSearchStrategy(ctx, roleStrategy, skillsMap) {
  const primaryRoles = roleStrategy.primaryTargetRoles
  const secondaryRoles = roleStrategy.secondaryTargetRoles.slice(0, 2)
  const topSkill = skillsMap.technicalSkills[0] || skillsMap.frontend[0] || skillsMap.backend[0] || ''

  // Every target role is searched: a cap here would drop the candidate's own targets silently.
  const jobSpySearchTerms = dedupe([...primaryRoles, ...secondaryRoles])

  const linkedinSearchQueries = primaryRoles.map((role) => {
    if (topSkill) return `"${role}" AND (${topSkill})`
    return `"${role}"`
  }).slice(0, 6)

  const willRelocate = ctx.relocation && ctx.relocation !== 'none'
  const locations = dedupe([
    ctx.location,
    ...ctx.preferredLocations,
    ...(willRelocate ? RELOCATION_REGIONS : []),
  ]).filter(Boolean)
  const remoteLabel = ctx.remotePreference || 'flexible'

  const recommendedSearchQueries = []
  for (const role of primaryRoles.slice(0, 3)) {
    for (const loc of locations.slice(0, 2)) {
      recommendedSearchQueries.push(`${role} ${loc} ${remoteLabel}`.trim())
    }
    if (locations.length === 0) {
      recommendedSearchQueries.push(`${role} ${remoteLabel}`.trim())
    }
  }

  const locationFilters = locations.length ? locations : ['Remote']

  const remoteFilters = REMOTE_MAP[ctx.remotePreference] || REMOTE_MAP.flexible

  return {
    recommendedSearchQueries: dedupe(recommendedSearchQueries).slice(0, 10),
    linkedinSearchQueries,
    jobSpySearchTerms,
    locationFilters,
    remoteFilters,
  }
}
