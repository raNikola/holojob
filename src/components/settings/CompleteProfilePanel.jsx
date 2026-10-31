import Card from '../ui/Card'
import Button from '../ui/Button'
import { useProfile } from '../../context/ProfileContext'
import { openQuestionnaire } from '../../modules/appNavigation'
import { unansweredQuestionIds } from '../../modules/profile/questionnaireStatus'

export default function CompleteProfilePanel() {
  const { profile } = useProfile()
  const left = unansweredQuestionIds(profile).length
  return (
    <Card title="Complete your profile">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        {left === 0
          ? 'Every questionnaire question is answered.'
          : `${left} questionnaire question${left === 1 ? '' : 's'} unanswered. Unanswered means unknown: it lowers how sure matching is, never a score.`}
      </p>
      {left > 0 && <Button variant="secondary" onClick={openQuestionnaire}>Open the questionnaire</Button>}
    </Card>
  )
}
