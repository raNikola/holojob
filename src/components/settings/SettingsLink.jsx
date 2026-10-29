import { openSettings } from '../../modules/appNavigation'

/** An inline link that opens Settings on the named registry section. */
export default function SettingsLink({ section, children }) {
  return (
    <button type="button" onClick={() => openSettings(section)} className="underline underline-offset-2 hover:text-teal-700 dark:hover:text-teal-300">
      {children}
    </button>
  )
}
