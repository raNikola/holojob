import { useEffect, useRef, useState } from 'react'
import Card from '../ui/Card'
import QuestionField from './QuestionField'
import { QUESTION_COUNT } from '../../data/questions'
import { HIGH_IMPACT_QUESTION_IDS, confirmedQuestionIds, derivedEntry, isDerivedAnswer, orderedQuestions } from '../../modules/profile/questionnaireStatus'
import { SKILLS_DICTIONARY } from '../../data/skillsDictionary'
import { useProfile } from '../../context/ProfileContext'
import { useRepoScan } from '../../hooks/useRepoScan'
import { ensureApiAvailable } from '../../utils/apiAvailability'
import { joinAnswerList, parseAnswerList } from '../../utils/answerList'

// SKILLS QUESTION IDs
const SKILL_QS = [2, 5]

/** Build the canonical set of skills to pre-select from all sources */
function buildAutoSkills(parsedSkills = [], candidateIntel = null, projectIntel = null) {
  const all = new Set()

  // 1. From resume parsed skills
  for (const s of parsedSkills) if (s) all.add(s)

  // 2. From candidate-intelligence skillsMap
  if (candidateIntel?.skillsMap) {
    for (const arr of Object.values(candidateIntel.skillsMap)) {
      if (Array.isArray(arr)) arr.forEach((s) => s && all.add(s))
    }
  }

  // 3. From project intelligence aggregate techStack
  if (projectIntel?.aggregate?.techStack) {
    for (const s of projectIntel.aggregate.techStack) if (s) all.add(s)
  }
  if (projectIntel?.projects) {
    for (const p of projectIntel.projects) {
      for (const s of (p.techStack || [])) if (s) all.add(s)
    }
  }

  // Keep only skills known in the dictionary (with case-insensitive match)
  const dictLower = new Map(SKILLS_DICTIONARY.map((s) => [s.toLowerCase(), s]))
  const matched = []
  for (const raw of all) {
    const canonical = dictLower.get(raw.toLowerCase())
    if (canonical) matched.push(canonical)
  }
  return [...new Set(matched)]
}

/** Build project entries from repo intelligence for Q4 */
function buildRepoProjects(projectIntel = null) {
  if (!projectIntel?.projects?.length) return []
  return projectIntel.projects
    .filter((p) => p.name)
    .map((p) => {
      const summary = p.summary ? ` — ${p.summary}` : ''
      return `${p.name}${summary}`
    })
}

/** Fetch JSON from the local API, returns null on error */
async function fetchJson(url) {
  if (!(await ensureApiAvailable())) return null
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

const ORDERED_QUESTIONS = orderedQuestions()

export default function QuestionnaireForm({ questionIndex = 0, onJumpToQuestion }) {
  const { profile, updateProfile } = useProfile()
  const [candidateIntel, setCandidateIntel] = useState(null)
  const { projectIntel, canScan: hasRepos } = useRepoScan(profile)
  const seeded = useRef(false)

  // Load both intelligence files once on mount
  useEffect(() => {
    fetchJson('/api/intelligence/candidate').then((cand) => {
      if (cand) setCandidateIntel(cand)
    })
  }, [])

  // Auto-seed skill questions once intelligence is loaded
  useEffect(() => {
    if (seeded.current) return
    const parsedSkills = profile.resume?.parsedData?.skills || []
    if (!parsedSkills.length && !candidateIntel && !projectIntel) return

    const autoSkills = buildAutoSkills(parsedSkills, candidateIntel, projectIntel)
    if (!autoSkills.length) return

    let didSeed = false
    updateProfile((prev) => {
      const answers = [...prev.questionnaire.answers]
      for (const qid of SKILL_QS) {
        const idx = answers.findIndex((a) => a.id === qid)
        const current = idx >= 0 ? answers[idx].answer || '' : ''
        // Only seed if there's no real answer yet (empty or a single leftover)
        if (parseAnswerList(current).length > 1) continue
        const entry = derivedEntry(qid, `Q${qid}`, joinAnswerList(autoSkills))
        if (idx >= 0) answers[idx] = entry
        else answers.push(entry)
        didSeed = true
      }
      if (!didSeed) return prev
      answers.sort((a, b) => a.id - b.id)
      return { ...prev, questionnaire: { answers } }
    })
    seeded.current = true
  }, [candidateIntel, projectIntel, profile.resume?.parsedData?.skills, updateProfile])

  const getAnswer = (id) => {
    const found = profile.questionnaire.answers.find((a) => a.id === id)
    return found?.answer || ''
  }

  const isDerived = (id) => isDerivedAnswer(profile.questionnaire.answers.find((a) => a.id === id))

  const setAnswer = (id, question, answer) => {
    updateProfile((prev) => {
      const answers = [...prev.questionnaire.answers]
      const idx = answers.findIndex((a) => a.id === id)
      // Clearing an answer removes it: an empty entry would read as an answer.
      if (!isNonEmpty(answer)) {
        if (idx >= 0) answers.splice(idx, 1)
        return { ...prev, questionnaire: { answers } }
      }
      const entry = { id, question, answer }
      if (idx >= 0) answers[idx] = entry
      else answers.push(entry)
      answers.sort((a, b) => a.id - b.id)
      return { ...prev, questionnaire: { answers } }
    })
  }

  const currentQuestion = ORDERED_QUESTIONS[questionIndex]
  const highImpact = HIGH_IMPACT_QUESTION_IDS.includes(currentQuestion?.id)
  const confirmed = new Set(confirmedQuestionIds(profile))
  const answeredCount = confirmed.size
  const repoProjects = buildRepoProjects(projectIntel)
  const allParsedSkills = buildAutoSkills(
    profile.resume?.parsedData?.skills || [],
    candidateIntel,
    projectIntel,
  )

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          All of these are optional. Each one you answer gives matching more to go on; skip any and come back later. Role, location, remote and salary were captured on the Profile step.
        </p>

        {hasRepos && !projectIntel && (
          <p className="mt-3 text-xs text-stone-500">Scan your repos in the Repos step to pre-fill skills.</p>
        )}

        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between text-xs font-medium text-stone-500">
            <span>Question {questionIndex + 1} of {QUESTION_COUNT}</span>
            <span>{answeredCount}/{QUESTION_COUNT} answered</span>
          </div>
          <p className="mb-2 text-xs text-stone-500">
            {highImpact ? 'High impact on matching' : 'Adds detail'}
          </p>
          <div className="h-1.5 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-800">
            <div
              className="h-full rounded-full bg-teal-600 transition-all duration-300"
              style={{ width: `${(answeredCount / QUESTION_COUNT) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {onJumpToQuestion && (
        <div className="grid grid-cols-6 gap-1.5 sm:grid-cols-9" role="group" aria-label="Jump to question">
          {ORDERED_QUESTIONS.map((q, i) => {
            const answered = confirmed.has(q.id)
            const current = i === questionIndex
            return (
              <button
                key={q.id}
                type="button"
                onClick={() => onJumpToQuestion(i)}
                title={`Question ${i + 1}`}
                aria-label={`Question ${i + 1}, ${answered ? 'answered' : 'not answered'}`}
                aria-current={current ? 'step' : undefined}
                className={`rounded-md border px-2 py-1.5 text-xs font-medium transition-colors ${
                  current
                    ? 'border-teal-600 bg-teal-600 text-white'
                    : answered
                      ? 'border-teal-200 bg-teal-50 text-teal-800 hover:bg-teal-100 dark:border-teal-800 dark:bg-teal-900/30 dark:text-teal-200'
                      : 'border-stone-200 bg-white text-stone-500 hover:bg-stone-50 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-400'
                }`}
              >
                {i + 1}
              </button>
            )
          })}
        </div>
      )}

      {currentQuestion && (
        <Card className="!p-4">
          {isDerived(currentQuestion.id) && (
            <p className="mb-3 text-xs text-amber-700 dark:text-amber-300">
              Pre-filled from your skills, not confirmed by you. Change it, or press Continue to keep it as a suggestion.
            </p>
          )}
          <QuestionField
            question={currentQuestion}
            answer={getAnswer(currentQuestion.id)}
            onChange={(answer) => setAnswer(currentQuestion.id, currentQuestion.text, answer)}
            profile={profile}
            allParsedSkills={allParsedSkills}
            repoProjects={repoProjects}
          />
        </Card>
      )}
    </div>
  )
}

function isNonEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0
}
