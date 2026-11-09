// What the storage notice says (S8a). One place, so the wording is checked once against what `saveJobs` really keeps and drops.
// Kept in the browser, in every shape: notes, statuses, outreach, tracking, generated documents and AI insights (the `aiInsights` field).
// Reloaded from the server when dropped: the ad text, the extracted facts (`llmFacts`) and the engine details (`engineShadow`).

const KEPT = 'notes, statuses, outreach, tracking, generated documents and AI insights'

export const NEAR_NOTICE = (percent) =>
  `Your job list uses about ${percent}% of this browser's storage limit. Nothing has been dropped yet. If it grows past the limit, the browser will keep a shorter copy and load the ad text from the server.`

export const LEAN_NOTICE = `This browser can't hold the whole job list, so it keeps a shorter copy. Kept in this browser: ${KEPT}, and the text of kept, no-longer-listed and hand-entered jobs. Loaded from the server instead: the ad text of jobs from your latest search, and their extracted facts and engine details.`

export const MINIMAL_NOTICE = (count) =>
  `This browser is almost full, so it keeps a minimal copy. Kept in this browser: ${KEPT}, and the text of hand-entered jobs. Loaded from the server instead: the ad text of ${count} ${count === 1 ? 'job' : 'jobs'} (kept ones too, from your history when the page opens), and their extracted facts and engine details.`

export const ERROR_NOTICE =
  'Your job list could not be saved in this browser, even in its shortest form. What you change from now on is not saved here and will be lost when you reload this tab. The last saved copy is still in the browser.'

export const MISSING_NOTICE = (count) =>
  `${count} ${count === 1 ? 'ad' : 'ads'} could not be loaded with ${count === 1 ? 'its' : 'their'} text (your history was not reachable, or holds no text for ${count === 1 ? 'it' : 'them'}). Search, outreach and AI tools cannot read ${count === 1 ? 'that ad' : 'those ads'}' text until you reload. Nothing you wrote is affected.`

export const GATE_TEXT = (count) => `Loading the text of ${count} ${count === 1 ? 'ad' : 'ads'} from your history…`
