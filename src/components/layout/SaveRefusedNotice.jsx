import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Toast, ToastStack } from '../ui/Toast'
import { SAVE_REFUSED_EVENT, refusedNoticeText } from '../../modules/jobs/saveRefused.js'

/** A persistent error toast when the server refuses a save that would wipe filled-in settings (save guard). One per file; dismissable. */
export default function SaveRefusedNotice() {
  const [shown, setShown] = useState([])
  useEffect(() => {
    const onRefused = (event) => {
      const what = event.detail?.what === 'intelligence' ? 'intelligence' : 'profile'
      setShown((current) => (current.includes(what) ? current : [...current, what]))
    }
    window.addEventListener(SAVE_REFUSED_EVENT, onRefused)
    return () => window.removeEventListener(SAVE_REFUSED_EVENT, onRefused)
  }, [])
  return (
    <ToastStack>
      {shown.map((what) => (
        <Toast key={what} kind="error" onDismiss={() => setShown((current) => current.filter((w) => w !== what))}>
          <div className="flex gap-2" data-testid="save-refused-notice">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{refusedNoticeText(what)}</p>
          </div>
        </Toast>
      ))}
    </ToastStack>
  )
}
