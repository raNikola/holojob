// Whether the Jobs screen reads the server's list (docs/redesign/JOBS_LIST_SERVER_PLAN.md). Off until the screens that depended on the whole stored list work
// without it (P4) and the browser-only worked ads are in the list (requirement 8); the plan's last step (S6) turns it on and removes this file. The tests turn it on.
let active = false

export const isServerListActive = () => active
export const setServerListActive = (value) => { active = Boolean(value) }
