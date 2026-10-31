import Card from '../ui/Card'
import Button from '../ui/Button'
import SettingsLink from '../settings/SettingsLink'
import { unansweredQuestionIds } from '../../modules/profile/questionnaireStatus'

// "Complete your profile (N questions left)": shown while questions are unknown and not dismissed.
export function shouldShowCompleteProfile(profile) {
  return unansweredQuestionIds(profile).length > 0 && !profile?.meta?.completeProfileDismissedAt
}

export default function CompleteProfileCard({ profile, onAnswer, onDismiss }) {
  const left = unansweredQuestionIds(profile).length
  if (!shouldShowCompleteProfile(profile)) return null
  return (
    <Card title={`Complete your profile (${left} question${left === 1 ? '' : 's'} left)`}>
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Skipped questions are unknown, not wrong: matching simply has less to go on. Answer what you like, in any order.
        This is also under <SettingsLink section="complete-profile">Settings, Complete your profile</SettingsLink>.
      </p>
      <div className="flex gap-2">
        <Button onClick={onAnswer}>Answer them</Button>
        <Button variant="ghost" onClick={onDismiss}>Not now</Button>
      </div>
    </Card>
  )
}
