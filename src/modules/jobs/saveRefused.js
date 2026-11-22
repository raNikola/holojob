// A save the server refused because it would empty or cut settings that are filled in there (scripts/save-guard.js, answer 409).
// The sync functions announce it on `window`, so one notice (SaveRefusedNotice) shows it whichever screen made the save, also for the
// callers that do not look at the result. Nothing from the profile travels in the event: only which file it was.

export const SAVE_REFUSED_EVENT = 'holojob:save-refused'

/** @param {'profile' | 'intelligence'} what */
export function announceSaveRefused(what) {
  try {
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(SAVE_REFUSED_EVENT, { detail: { what } }))
  } catch {
    // no window (a test, a server render): the caller's own failure result still carries the refusal
  }
}

export const refusedNoticeText = (what) =>
  `The server refused to save your ${what}: it would empty or cut several settings that are filled in on the server. Nothing was changed. `
  + 'This browser may hold an empty or older copy, so do not save from it. Earlier versions are kept on the server in data/backups/auto.'
