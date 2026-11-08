// The Apply by column: how close an ad's stated deadline is, in days on the viewer's own calendar. Display only. A past date reads
// Expired; it does not close the ad and no score sees it.

const DAY = 24 * 60 * 60 * 1000
/** Sorted after every date still ahead, soonest-first; a row with no date is empty, so the table puts it last either way. */
const EXPIRED_FROM = 1_000_000

function localMidnight(value) {
  const date = new Date(value)
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** Midnight of the local day `now` falls in: what the table keeps, so the column only moves when the date does. */
export const dayOf = (now) => localMidnight(now)

function dateOf(job) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(job?.applyDeadline || job?.expiresAt || ''))
  if (!match) return null
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const date = new Date(year, month - 1, day)
  return date.getMonth() === month - 1 && date.getDate() === day ? date.getTime() : null
}

function daysLeft(job, today) {
  const time = dateOf(job)
  return time === null ? null : Math.round((time - localMidnight(today)) / DAY)
}

const SOURCE_NOTE = { board: 'The job board\'s own expiry date', ad_text: 'The date stated in the ad' }

/** `{ key, label, variant, note }`. `variant` is a Badge variant; null means plain text. */
export function deadlineStatus(job, today) {
  const days = daysLeft(job, today)
  if (days === null) return { key: 'unknown', label: 'Not specified', variant: null, note: '' }
  const note = SOURCE_NOTE[job.applyDeadlineSource] ?? SOURCE_NOTE.board
  if (days < 0) return { key: 'expired', label: 'Expired', variant: 'low', note: `${note} has passed. The ad is not marked closed for that.` }
  if (days <= 1) return { key: 'critical', label: days === 0 ? 'Today' : 'Tomorrow', variant: 'warn', note }
  if (days <= 3) return { key: 'warning', label: `In ${days} days`, variant: 'medium', note }
  if (days <= 7) return { key: 'upcoming', label: `In ${days} days`, variant: 'derived', note }
  return { key: 'later', label: new Date(dateOf(job)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }), variant: null, note }
}

/** The sort value: days left, expired ones after them, and null with no date. */
export function deadlineSortValue(job, today) {
  const days = daysLeft(job, today)
  if (days === null) return null
  return days < 0 ? EXPIRED_FROM - days : days
}
