import { QUESTIONS } from '../../data/questions.js'

// A question is unknown until it has a non-empty answer. Nothing is stored for
// a skipped question, so this list is always derived, never kept.
const hasAnswer = (entry) => typeof entry?.answer === 'string' && entry.answer.trim().length > 0

// Questions that move matching most, asked first. The rest keep their order.
export const HIGH_IMPACT_QUESTION_IDS = [10, 11, 12, 2, 5, 4, 17]

export function answeredQuestionIds(profile) {
  const answers = profile?.questionnaire?.answers || []
  return QUESTIONS.filter((q) => hasAnswer(answers.find((a) => a.id === q.id))).map((q) => q.id)
}

export function unansweredQuestionIds(profile) {
  const answered = new Set(answeredQuestionIds(profile))
  return QUESTIONS.filter((q) => !answered.has(q.id)).map((q) => q.id)
}

// The questionnaire in the order it is asked: high-impact questions first.
export function orderedQuestions() {
  const rank = (id) => {
    const i = HIGH_IMPACT_QUESTION_IDS.indexOf(id)
    return i === -1 ? HIGH_IMPACT_QUESTION_IDS.length : i
  }
  return QUESTIONS.map((q, i) => ({ q, i })).sort((a, b) => rank(a.q.id) - rank(b.q.id) || a.i - b.i).map(({ q }) => q)
}

// An answer filled in from the résumé rather than typed or chosen by the user.
// Editing it replaces the entry without this field, which confirms it.
export const DERIVED_FROM_RESUME = 'resume'

export const derivedEntry = (id, question, answer) => ({ id, question, answer, source: DERIVED_FROM_RESUME })

export const isDerivedAnswer = (entry) => entry?.source === DERIVED_FROM_RESUME

// Answers the user typed or chose: answered and not pre-filled from the résumé.
// Pre-filled answers stay stored and shown as suggestions but do not count.
export function confirmedQuestionIds(profile) {
  const answers = profile?.questionnaire?.answers || []
  return QUESTIONS.filter((q) => {
    const entry = answers.find((a) => a.id === q.id)
    return hasAnswer(entry) && !isDerivedAnswer(entry)
  }).map((q) => q.id)
}
