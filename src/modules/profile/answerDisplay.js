import { QUESTIONS } from '../../data/questions'
import { repairCommaAnswer } from '../../utils/answerList'

const LIST_TYPES = new Set(['skills', 'multi', 'projects'])

/** Entries of a stored list answer, repeats dropped, whole sentences kept. */
export function splitListAnswer(answer, knownEntries = []) {
  return repairCommaAnswer(answer, knownEntries)
}

/** How the Profile page should draw one stored answer. */
export function describeAnswer(answer, profile) {
  const question = QUESTIONS.find((q) => q.id === answer.id)
  const text = (answer.answer || '').trim()
  const label = question?.text || answer.question
  if (!text) return null
  if (question && LIST_TYPES.has(question.type)) {
    const known = question.type === 'projects' ? profile?.resume?.parsedData?.projects || [] : []
    const items = splitListAnswer(text, known)
    // A project entry is a sentence, a tag is a word or two.
    const kind = items.some((i) => i.length > 60) ? 'bullets' : 'chips'
    return { id: answer.id, label, kind, items }
  }
  return { id: answer.id, label, kind: question?.type === 'textarea' ? 'prose' : 'text', text }
}
