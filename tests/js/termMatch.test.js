import { describe, expect, it } from 'vitest'
import { SKILLS_DICTIONARY } from '../../src/data/skillsDictionary'
import { matchSkillToBucket } from '../../src/modules/intelligence/skillBuckets'
import { classifySkills } from '../../src/modules/intelligence/skillsClassifier'
import { containsTerm } from '../../src/utils/termMatch'
import { extractProfileFromResume } from '../../src/utils/profileExtractor'

const skillsIn = (text) => extractProfileFromResume(text).parsedData.skills

describe('containsTerm', () => {
  it('does not find a short name inside a longer word', () => {
    expect(containsTerm('Google Cloud', 'Go')).toBe(false)
    expect(containsTerm('Digitalni marketing', 'Git')).toBe(false)
    expect(containsTerm('rad sa ego stanjem deteta', 'Go')).toBe(false)
    expect(containsTerm('Django developer', 'Go')).toBe(false)
    expect(containsTerm('trust and frustration', 'Rust')).toBe(false)
    expect(containsTerm('Rubyist', 'Ruby')).toBe(false)
    expect(containsTerm('studios and scenarios', 'iOS')).toBe(false)
    expect(containsTerm('laws and draws', 'AWS')).toBe(false)
    expect(containsTerm('JavaScript', 'Java')).toBe(false)
    expect(containsTerm('MySQL and NoSQL', 'SQL')).toBe(false)
    expect(containsTerm('Sassy', 'SASS')).toBe(false)
    expect(containsTerm('go-to-market strategy', 'Go')).toBe(false)
  })

  it('finds a whole term, however it is punctuated', () => {
    expect(containsTerm('Backend in Go, Python', 'Go')).toBe(true)
    expect(containsTerm('Skills: Go.', 'Go')).toBe(true)
    expect(containsTerm('git and GitHub', 'Git')).toBe(true)
    expect(containsTerm('(Rust)', 'Rust')).toBe(true)
    expect(containsTerm('Used iOS and Android', 'iOS')).toBe(true)
    expect(containsTerm('Deployed on AWS/GCP', 'AWS')).toBe(true)
  })

  it('keeps names that contain symbols', () => {
    expect(containsTerm('Wrote C++ and C# services', 'C++')).toBe(true)
    expect(containsTerm('Wrote C++ and C# services', 'C#')).toBe(true)
    expect(containsTerm('Built with Node.js, React', 'Node.js')).toBe(true)
    expect(containsTerm('Next.js app', 'Next.js')).toBe(true)
    expect(containsTerm('Pipelines: CI/CD and Docker', 'CI/CD')).toBe(true)
  })

  it('does not read C inside C++ or C#', () => {
    expect(containsTerm('C++ and C#', 'C')).toBe(false)
    expect(containsTerm('Languages: C, Rust', 'C')).toBe(true)
  })

  it('matches Cyrillic and accented text on the same rules', () => {
    expect(containsTerm('Знање Git и Python', 'Git')).toBe(true)
    expect(containsTerm('Дигитални маркетинг', 'Git')).toBe(false)
  })

  it('returns false for an empty term or text', () => {
    expect(containsTerm('anything', '')).toBe(false)
    expect(containsTerm('', 'Go')).toBe(false)
  })

  it('finds each dictionary skill written alone, and none of them inside "xx<skill>xx"', () => {
    for (const skill of SKILLS_DICTIONARY) {
      expect(containsTerm(`Skills: ${skill}, other`, skill), skill).toBe(true)
      if (/^\p{L}/u.test(skill)) expect(containsTerm(`xx${skill}xx`, skill), `inside ${skill}`).toBe(false)
    }
  })
})

describe('extractProfileFromResume skills', () => {
  it('finds no Go or Git in a CV that only has Google, ego and Digitalni', () => {
    const text = 'Rad na računaru: Google Cloud, ChatGPT\nrad sa ego stanjem deteta\nDigitalni marketing, 2022'
    expect(skillsIn(text)).toEqual([])
  })

  it('still finds Go and Git when the CV lists them', () => {
    expect(skillsIn('Skills: Go, Git, Docker')).toEqual(expect.arrayContaining(['Go', 'Git', 'Docker']))
  })

  it('finds C++ and C# written with their symbols', () => {
    expect(skillsIn('Languages: C++, C#, Python')).toEqual(expect.arrayContaining(['C++', 'C#', 'Python']))
  })

  it('does not take JavaScript for Java, or NoSQL for SQL', () => {
    const found = skillsIn('JavaScript and NoSQL')
    expect(found).not.toContain('Java')
    expect(found).not.toContain('SQL')
  })
})

describe('skill classification', () => {
  it('does not file "Google Cloud" or "Digitalni marketing" under a language bucket by substring', () => {
    expect(matchSkillToBucket('Google Cloud')).toBe('cloudDevOps')
    expect(matchSkillToBucket('Digitalni marketing')).toBeNull()
  })

  it('does not call a non-technical phrase technical because it contains a short skill name', () => {
    const map = classifySkills({
      questionnaire: { technicalSkills: ['Digitalni marketing', 'Python'], technologies: [], productBusiness: [], culturePreference: [], leadershipExamples: [], recruiterPerception: [], candidateStrengths: [] },
      parsedData: { skills: [] },
      allSkills: ['Digitalni marketing', 'Python'],
    })
    expect(map.technicalSkills).toContain('Python')
    expect(map.technicalSkills).not.toContain('Digitalni marketing')
  })
})
