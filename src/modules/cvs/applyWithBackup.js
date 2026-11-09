export const BACKUP_FAILED = 'The backup of your current profile could not be made, so nothing was changed. Check that the server is running and try again.'

/**
 * Applies AI-suggested changes to the profile only after the server has verified a backup of the profile as it is now
 * (the same backup the import takes, `backupProfileForImport`). A backup that fails, throws or is not confirmed changes nothing.
 * @param {{ profile: object, backup: (profile: object) => Promise<boolean>, apply: () => any }} args
 */
export async function applyWithBackup({ profile, backup, apply }) {
  const backedUp = await Promise.resolve().then(() => backup(profile)).then((ok) => ok === true, () => false)
  if (!backedUp) return { ok: false, stage: 'backup', message: BACKUP_FAILED }
  return { ok: true, result: apply() }
}
