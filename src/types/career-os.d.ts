/**
 * Career OS core data shapes (JSDoc / IDE assistance).
 */

/** @typedef {'P1' | 'P2' | 'P3' | 'Reject'} JobPriority */

/** @typedef {'none' | 'draft' | 'ready' | 'sent'} OutreachStatus */

/**
 * @typedef {Object} ScoringWeights
 * @property {number} roleMatch
 * @property {number} skillMatch
 * @property {number} industryMatch
 * @property {number} experienceMatch
 * @property {number} locationMatch
 * @property {number} cultureMatch
 */

/**
 * @typedef {Object} BasicProfile
 * @property {string} fullName
 * @property {string} email
 * @property {string} [phone]
 * @property {string} [location]
 * @property {string} [currentRole]
 * @property {string} [experienceYears]
 * @property {string[]} [targetRoles]
 * @property {string[]} [preferredLocations]
 * @property {string} [remotePreference]
 * @property {string} [salaryExpectation]
 * @property {number|null} [minSalaryEur] EUR per month; display only
 * @property {number|null} [desiredSalaryMinEur]
 * @property {number|null} [desiredSalaryMaxEur]
 * @property {string} [linkedin]
 * @property {LanguageEntry[]} [languages]
 * @property {WorkAuthorization} [workAuthorization]
 * @property {string[]} [allowedLocations] Country, region or REMOTE codes; empty gates nothing.
 * @property {'none' | 'abroad' | 'anywhere'} [relocation]
 */

/**
 * @typedef {Object} WorkAuthorization
 * @property {{ jurisdiction: string, basis: 'citizen' | 'permanent_resident' | 'work_permit' | 'other' | '' }[]} holds
 *   Where the candidate may work without sponsorship: ISO country codes, or EU.
 * @property {boolean} openToSponsorship
 */

/**
 * @typedef {Object} LanguageEntry
 * @property {string} language
 * @property {'native' | 'fluent' | 'advanced' | 'intermediate' | 'basic' | ''} proficiency
 */

/**
 * @typedef {Object} Profile
 * @property {BasicProfile} basicProfile
 * @property {Object} resume
 * @property {Object} repositories
 * @property {Object} questionnaire
 * @property {Object} [meta]
 */

/**
 * @typedef {Object} CandidateIntelligence
 * @property {Object} candidateSummary
 * @property {Object} roleStrategy
 * @property {Object} skillsMap
 * @property {Object} experienceMap
 * @property {Object} jobFitPreferences
 * @property {string[]} candidateStrengths
 * @property {string[]} candidateWeaknesses
 * @property {string[]} resumeKeywords
 * @property {Object} atsKeywordBank
 * @property {Object} searchStrategy
 * @property {string[]} languages Derived from basicProfile.languages, e.g. "Serbian (native)".
 * @property {ScoringWeights} scoringWeights
 * @property {Object} [meta]
 */

/**
 * @typedef {Object} OutreachContact
 * @property {string} id
 * @property {string} name
 * @property {string} [title]
 * @property {string} [company]
 * @property {string} [linkedinUrl]
 * @property {string} [email]
 * @property {'recruiter' | 'hiring_manager' | 'employee' | 'manual' | 'unknown'} [role]
 * @property {number} [relevanceScore]
 * @property {string} [source]
 */

/**
 * @typedef {Object} Job
 * @property {string} jobId
 * @property {string} title
 * @property {string} company
 * @property {string} [location]
 * @property {string} [description]
 * @property {string} [jobUrl]
 * @property {boolean} [isRemote]
 * @property {string} [provider]
 * @property {number} [matchScore]
 * @property {string} [matchLabel]
 * @property {JobPriority} [priority]
 * @property {string} [applyRecommendation]
 * @property {string[]} [matchedSkills]
 * @property {string[]} [missingSkills]
 * @property {string[]} [redFlags]
 * @property {Object} [scoreBreakdown]
 * @property {Object} [outreach]
 * @property {Object} [application]
 * @property {Object} [tailoredAssets]
 */

/**
 * @typedef {Object} ApplicationStatus
 * @property {'saved' | 'applied' | 'interviewing' | 'offer' | 'rejected' | 'withdrawn'} stage
 * @property {string} [appliedAt]
 * @property {string} [notes]
 * @property {string} [followUpAt]
 */

export {}
