/** The sentence typed before the LinkedIn cookie may be entered (deep mode can get the account banned). */
export const LINKEDIN_RISK_PHRASE = 'i understand'

/** True when the risk box is ticked and the phrase is typed (case and surrounding spaces ignored). */
export function linkedInRiskConfirmed({ accepted, typed }) {
  return accepted === true && String(typed ?? '').trim().toLowerCase() === LINKEDIN_RISK_PHRASE
}
